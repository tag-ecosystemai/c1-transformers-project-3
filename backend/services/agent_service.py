"""
The shipment investigation, orchestrated as a LangGraph workflow.

    get_delay_risk
        |-- failed ------------------------------------------> END
        |-- LOW risk --> investigation_not_required ---------> END
        v
    get_shipment --- failed ---------------------------------> END
        v
    evidence sources, in order (EVIDENCE_SOURCES)
        get_historical_delay_context
        get_destination_weather
        get_inventory_coverage
        find_alternative_supplier
        (an optional failure becomes a limitation; any other
         failure ends the investigation)
        v
    generate_briefing ---------------------------------------> END

Three concerns are kept apart:

- Business rules live in the services: the prediction service decides
  whether a shipment requires investigation, and each tool decides
  what its evidence is.
- The graph owns orchestration: the investigation state, the order of
  the steps, routing on the risk decision, and what a failure means
  for the rest of the investigation.
- Reasoning over the evidence happens in the briefing step, which is
  where retrieved knowledge and an LLM will take part.

Callers use iter_investigation() and run_investigation(). The graph
and its state stay inside this module and are never sent to a client.
"""

import logging
import operator
from contextlib import closing
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Any, Callable, Generator, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from backend.models.schemas import (
    DisruptionBriefingResponse,
    InventoryStatusResponse,
    PredictionResponse,
    ShipmentResponse,
    SupplierRecommendation,
    ToolCall,
    ToolCallStatus,
    ToolEvidence,
)
from backend.exceptions import (
    InvestigationNotRequiredError,
    WeatherServiceError,
)
from backend.services.agent_tools import (
    get_alternative_suppliers,
    get_delay_risk,
    get_destination_weather,
    get_historical_delay_context,
    get_inventory_coverage,
    get_shipment,
)
from backend.services.briefing_service import generate_rag_briefing


logger = logging.getLogger(__name__)


# Applies to every briefing, whether or not weather was collected.
WEATHER_SCOPE_LIMITATION = (
    "Weather describes the geocoded destination city over an approximate "
    "window (order date plus scheduled shipping days), not the full "
    "shipment route."
)

# Recorded whenever an inventory record is collected. The record is
# matched on product name only, so it describes the product and never
# the stock available to this shipment.
INVENTORY_SCOPE_LIMITATION = (
    "Inventory record available; stock availability for this shipment "
    "has not been verified."
)

# Reported in place of an inventory failure's own message, which can
# name server files and is only written to the log.
INVENTORY_UNAVAILABLE = (
    "No inventory record could be retrieved for this product."
)

# What the trace records of an inventory record. The warehouse and
# supplier on a record are unrelated to the shipment, and the reorder
# point and replenishment date cannot be related to it, so none of
# them is reported.
INVENTORY_TRACE_FIELDS = frozenset(
    {
        "product_name",
        "current_stock",
        "reserved_stock",
        "available_stock",
        "daily_demand",
        "safety_stock",
        "incoming_quantity",
        "inventory_coverage_days",
        "stockout_risk",
        "below_safety_stock",
        "matched_on",
        "data_source",
    }
)

# Recorded whenever supplier candidates are collected. Candidates are
# matched on product category only: the supplier dataset holds no
# available capacity, commercial terms, live status or delivery dates,
# and no link to the shipment or its current supplier.
SUPPLIER_SCOPE_LIMITATION = (
    "Supplier candidates are category-level suggestions; supplier "
    "availability, capacity, commercial terms and delivery dates have "
    "not been verified, and human approval is required before "
    "changing suppliers."
)

# Reported in place of a supplier failure's own message, which can
# name server files and is only written to the log.
SUPPLIER_UNAVAILABLE = (
    "No alternative supplier candidate could be retrieved for this "
    "shipment's product category."
)

# What the trace records of each supplier candidate: who it is, where
# it is, what it supplies, and the recorded figures the suggestion is
# explained by. Cancellation, quality-issue and capacity-utilization
# rates are not reported: they explain nothing a reader is told, and a
# utilization figure invites a conclusion about spare capacity that the
# records cannot support.
SUPPLIER_CANDIDATE_TRACE_FIELDS = frozenset(
    {
        "supplier_id",
        "supplier_name",
        "supplier_country",
        "product_category",
        "average_lead_time_days",
        "on_time_delivery_rate",
        "supplier_risk_score",
        "supplier_risk_level",
        "data_source",
    }
)

# How candidates are found and how one comes to be suggested, as the
# supplier service does it.
SUPPLIER_MATCHED_ON = (
    "product category (the shipment's category or a listed compatible "
    "supplier category)"
)

SUPPLIER_SELECTION_BASIS = (
    "Candidates are ranked by the supplier service: a supplier country "
    "matching the shipment destination first, then lower supplier risk "
    "and recorded performance. The suggested candidate is the "
    "highest-ranked one with LOW or MEDIUM supplier risk."
)

# Evidence that this version of the investigation does not collect
# yet. Every evidence field now has a source, so there is none.
UNCOLLECTED_EVIDENCE_LIMITATIONS: list[str] = []


# Progress events reported while an investigation runs.
TOOL_START = "tool_start"
TOOL_COMPLETE = "tool_complete"
TOOL_ERROR = "tool_error"
MESSAGE = "message"
DONE = "done"


@dataclass(frozen=True)
class InvestigationEvent:
    """
    One step of an investigation, reported as it happens.

    ``data`` is JSON-serializable so the event can be sent to a client
    without further conversion.
    """

    event: str
    data: dict[str, Any]


def _tool_event(event: str, call: ToolCall) -> InvestigationEvent:
    """
    Describe a finished tool call as a progress event.

    The payload is the recorded ToolCall itself, with the tool under
    "name", so progress events and the final tool_trace cannot disagree.
    """
    data = call.model_dump(mode="json", exclude={"tool"})
    return InvestigationEvent(event, {"name": call.tool, **data})


# ============================================================
# INVESTIGATION STATE
# ============================================================


class InvestigationStatus(str, Enum):
    """How an investigation ended. Unset while it is still running."""

    NOT_REQUIRED = "not_required"
    FAILED = "failed"
    COMPLETED = "completed"


def _merge_evidence(current: ToolEvidence, new: ToolEvidence) -> ToolEvidence:
    """Add the evidence a step collected to what is already known."""
    return current.model_copy(update=new.model_dump(exclude_none=True))


class InvestigationState(TypedDict, total=False):
    """
    Everything known about one investigation.

    Each step returns only what it learned. tool_trace and limitations
    grow in the order the steps ran, and evidence is merged field by
    field, so a step never has to know what ran before it.
    """

    # The shipment reference as the caller gave it.
    shipment_id: str
    prediction: PredictionResponse
    shipment: ShipmentResponse
    evidence: Annotated[ToolEvidence, _merge_evidence]
    tool_trace: Annotated[list[ToolCall], operator.add]
    limitations: Annotated[list[str], operator.add]
    briefing: DisruptionBriefingResponse
    status: InvestigationStatus
    # The original exception when status is FAILED, kept as raised so
    # callers classify it exactly as before.
    failure: Exception


def _shipment_reference(state: InvestigationState) -> str:
    """
    The reference each step uses for the shipment.

    Once the risk is known this is the normalized reference from the
    prediction (for example "shp-1 " becomes "SHP-1"), so every later
    tool call and the briefing refer to the same shipment.
    """
    prediction = state.get("prediction")
    return prediction.shipment_id if prediction else state["shipment_id"]


def _tool_input(state: InvestigationState) -> dict[str, Any]:
    """The arguments recorded for a tool call made from this state."""
    return {"shipment_id": _shipment_reference(state)}


# ============================================================
# TOOL EXECUTION
# ============================================================


def _run_tool(
    tool: str,
    tool_input: dict[str, Any],
    function: Callable[[], Any],
    trace_output: Callable[[Any], Any] | None = None,
) -> tuple[ToolCall, Any, Exception | None]:
    """
    Run one tool and describe the call for the trace.

    Returns the recorded call, the tool's result and the exception it
    raised, if any. The tool is passed as a zero-argument callable so
    its failure happens here and is recorded; the calling step decides
    whether the investigation can continue. Outputs are stored in JSON
    form so the trace can be returned in the API response.

    The trace records the whole result unless trace_output chooses what
    is recorded of it.
    """
    try:
        result = function()
        recorded = result if trace_output is None else trace_output(result)
    except Exception as exc:
        call = ToolCall(
            tool=tool,
            input=tool_input,
            status=ToolCallStatus.ERROR,
            error=str(exc),
        )
        return call, None, exc

    output = (
        recorded.model_dump(mode="json")
        if isinstance(recorded, BaseModel)
        else recorded
    )

    call = ToolCall(
        tool=tool,
        input=tool_input,
        output=output,
        status=ToolCallStatus.SUCCESS,
    )
    return call, result, None


def _failed(error: Exception, call: ToolCall | None = None) -> InvestigationState:
    """The state update for a failure that ends the investigation."""
    update: InvestigationState = {
        "status": InvestigationStatus.FAILED,
        "failure": error,
    }
    if call is not None:
        update["tool_trace"] = [call]
    return update


def _summarize_shipment(shipment: ShipmentResponse) -> str:
    return (
        f"{shipment.shipment_reference}: {shipment.quantity} x "
        f"{shipment.product_name} ({shipment.category}) to "
        f"{shipment.destination_city}, {shipment.destination_country} "
        f"by {shipment.shipping_mode}, scheduled for "
        f"{shipment.scheduled_shipping_days} days, ordered "
        f"{shipment.order_date:%Y-%m-%d}."
    )


def _summarize_historical_context(context: dict[str, Any]) -> str:
    rates = context["historical_delay_rates"]
    return (
        f"Historical delay rates: product {rates['product']:.1%}, "
        f"market {rates['market']:.1%}, "
        f"shipping mode {rates['shipping_mode']:.1%}. "
        f"Highest: {context['highest_delay_rate_factor']}."
    )


def _summarize_weather(weather: dict[str, Any]) -> str:
    return (
        f"Observed weather in {weather['destination']}, "
        f"{weather['window_start']} to {weather['window_end']}: "
        f"{weather['precipitation_total_mm']:.1f} mm precipitation "
        f"(max {weather['precipitation_max_mm']:.1f} mm/day), "
        f"max wind {weather['max_wind_speed_kmh']:.1f} km/h; worst "
        f"condition {weather['worst_weather_description']} "
        f"({weather['severity']} severity)."
    )


def _format_coverage(days: float) -> str:
    """Coverage exactly as recorded: fractions are never rounded away."""
    amount = str(int(days)) if days.is_integer() else str(days)
    return f"{amount} day" if days == 1 else f"{amount} days"


def _summarize_inventory(record: InventoryStatusResponse) -> str:
    summary = (
        f"Inventory record for '{record.product_name}': "
        f"{record.available_stock} units available "
        f"({record.current_stock} in stock, {record.reserved_stock} "
        f"reserved) against average demand of {record.daily_demand} "
        "units per day, about "
        f"{_format_coverage(record.inventory_coverage_days)} of coverage."
    )
    if record.below_safety_stock:
        summary += (
            " Available stock is at or below the safety-stock level of "
            f"{record.safety_stock} units."
        )
    if record.incoming_quantity > 0:
        summary += f" {record.incoming_quantity} units are recorded as incoming."
    else:
        summary += " No incoming replenishment is recorded."

    return (
        f"{summary} Stockout risk on record: {record.stockout_risk.value}. "
        "This is a product-level record; stock availability for this "
        "shipment has not been verified."
    )


def _inventory_trace_output(record: InventoryStatusResponse) -> dict[str, Any]:
    return {
        **record.model_dump(mode="json", include=INVENTORY_TRACE_FIELDS),
        "limitation": INVENTORY_SCOPE_LIMITATION,
    }


def _summarize_supplier(recommendation: SupplierRecommendation) -> str:
    # Only what the supplier records hold is reported. A candidate is a
    # suggestion to review, never an available or committed supplier.
    if not recommendation.alternatives:
        raise ValueError("The supplier lookup returned no candidates.")

    count = recommendation.candidate_count
    compared = (
        f"{count} candidate{'' if count == 1 else 's'} on record for "
        "the category"
    )
    supplier = recommendation.recommended_supplier

    if supplier is None:
        return (
            "No alternative supplier is suggested for product category "
            f"'{recommendation.category}': the {compared} "
            f"{'is' if count == 1 else 'are'} classified as high risk "
            f"and {'needs' if count == 1 else 'need'} human review."
        )

    return (
        "Alternative supplier candidate for product category "
        f"'{recommendation.category}': {supplier.supplier_name} "
        f"({supplier.supplier_id}), based in {supplier.supplier_country}, "
        f"supplying {supplier.product_category}. On record: average "
        f"lead time {supplier.average_lead_time_days:g} days, on-time "
        f"delivery rate {supplier.on_time_delivery_rate:.1%}, supplier "
        f"risk {supplier.supplier_risk_level.value} "
        f"({supplier.supplier_risk_score:g}/100). It was selected from "
        f"{compared}. This is a category-level suggestion; supplier "
        "availability, capacity for the required quantity and "
        "commercial terms have not been verified."
    )


def _supplier_trace_output(
    recommendation: SupplierRecommendation,
) -> dict[str, Any]:
    # Enough to tell the candidates apart and explain the suggestion,
    # and no more. That capacity for the quantity is unverified stays
    # explicit, and the service's own note is replaced by the
    # limitation the briefing reports.
    def candidate(supplier: Any) -> dict[str, Any]:
        return supplier.model_dump(
            mode="json",
            include=SUPPLIER_CANDIDATE_TRACE_FIELDS,
        )

    suggested = recommendation.recommended_supplier

    return {
        "category": recommendation.category,
        "matched_on": SUPPLIER_MATCHED_ON,
        "selection_basis": SUPPLIER_SELECTION_BASIS,
        "candidate_count": recommendation.candidate_count,
        "recommended_supplier": (
            None if suggested is None else candidate(suggested)
        ),
        "alternatives": [
            candidate(supplier) for supplier in recommendation.alternatives
        ],
        "quantity_capacity_verified": recommendation.quantity_capacity_verified,
        "data_source": recommendation.data_source,
        "limitation": SUPPLIER_SCOPE_LIMITATION,
    }


# ============================================================
# EVIDENCE SOURCES
# ============================================================


@dataclass(frozen=True)
class EvidenceSource:
    """
    One source of evidence about a shipment under investigation.

    The graph gives every source its own step, in the order listed in
    EVIDENCE_SOURCES. Adding a source means adding an entry there.
    """

    # Name of the tool in the trace, in progress events and in the graph.
    tool: str
    collect: Callable[[ShipmentResponse], Any]
    # Turns the tool's result into the evidence fields it provides.
    summarize: Callable[[Any], ToolEvidence]
    # Start of the limitation recorded when the evidence is missing.
    limitation: str
    # Failures the investigation continues without. Any other failure
    # is a defect and ends the investigation.
    optional_errors: tuple[type[Exception], ...]
    # Limitations recorded whenever the evidence is collected.
    success_limitations: tuple[str, ...] = ()
    # Chooses what the trace records of the tool's result. Without it
    # the whole result is recorded.
    trace_output: Callable[[Any], Any] | None = None
    # Reported instead of a failure's own message, in the trace, in
    # progress events and in the limitation. The message is logged.
    public_error: str | None = None


# The tools are looked up when a step runs, not when this list is
# built, so the module's tool references can be replaced in tests.
EVIDENCE_SOURCES: tuple[EvidenceSource, ...] = (
    # Without historical context the briefing is still valid, so any
    # failure is reported as a limitation.
    EvidenceSource(
        tool="get_historical_delay_context",
        collect=lambda shipment: get_historical_delay_context(shipment),
        summarize=lambda context: ToolEvidence(
            historical_delay_summary=_summarize_historical_context(context)
        ),
        limitation="Historical delay context was not collected",
        optional_errors=(Exception,),
    ),
    # An external API outage must not block the investigation. Only
    # the weather service's own error is expected.
    EvidenceSource(
        tool="get_destination_weather",
        collect=lambda shipment: get_destination_weather(shipment),
        summarize=lambda weather: ToolEvidence(
            weather_summary=_summarize_weather(weather)
        ),
        limitation="Weather evidence was not collected",
        optional_errors=(WeatherServiceError,),
    ),
    # Nothing later depends on the inventory record, so no failure of
    # this step ends the investigation.
    EvidenceSource(
        tool="get_inventory_coverage",
        collect=lambda shipment: get_inventory_coverage(shipment),
        summarize=lambda record: ToolEvidence(
            inventory_summary=_summarize_inventory(record)
        ),
        limitation="Inventory evidence was not collected",
        optional_errors=(Exception,),
        success_limitations=(INVENTORY_SCOPE_LIMITATION,),
        trace_output=lambda record: _inventory_trace_output(record),
        public_error=INVENTORY_UNAVAILABLE,
    ),
    # Supplier candidates are suggestions for review. Nothing later
    # depends on them, so no failure of this step ends the
    # investigation: a category without candidates, an unreadable
    # dataset and a result with nothing usable all become a limitation.
    EvidenceSource(
        tool="find_alternative_supplier",
        collect=lambda shipment: get_alternative_suppliers(shipment),
        summarize=lambda recommendation: ToolEvidence(
            supplier_status=_summarize_supplier(recommendation)
        ),
        limitation="Supplier evidence was not collected",
        optional_errors=(Exception,),
        success_limitations=(SUPPLIER_SCOPE_LIMITATION,),
        trace_output=lambda recommendation: _supplier_trace_output(
            recommendation
        ),
        public_error=SUPPLIER_UNAVAILABLE,
    ),
)


# ============================================================
# GRAPH STEPS
# ============================================================


ASSESS_RISK = "get_delay_risk"
GET_SHIPMENT = "get_shipment"
INVESTIGATION_NOT_REQUIRED = "investigation_not_required"
GENERATE_BRIEFING = "generate_briefing"


def _assess_risk(state: InvestigationState) -> InvestigationState:
    """Ask the model for the delay risk and the risk gate decision."""
    shipment_id = state["shipment_id"]
    call, prediction, error = _run_tool(
        ASSESS_RISK,
        _tool_input(state),
        lambda: get_delay_risk(shipment_id),
    )
    if error is not None:
        return _failed(error, call)

    return {"tool_trace": [call], "prediction": prediction}


def _investigation_not_required(state: InvestigationState) -> InvestigationState:
    """LOW-risk shipments do not require AI investigation."""
    return {"status": InvestigationStatus.NOT_REQUIRED}


def _get_shipment(state: InvestigationState) -> InvestigationState:
    """
    Fetch the shipment facts. Required: every later step needs the
    shipment record, so a failure here ends the investigation.
    """
    shipment_reference = _shipment_reference(state)
    call, shipment, error = _run_tool(
        GET_SHIPMENT,
        _tool_input(state),
        lambda: get_shipment(shipment_reference),
    )
    if error is not None:
        return _failed(error, call)

    # A summary that cannot be built is a failure of this step, reported
    # after the tool call it follows rather than raised past the graph.
    try:
        evidence = ToolEvidence(shipment_summary=_summarize_shipment(shipment))
    except Exception as exc:
        return _failed(exc, call)

    return {"tool_trace": [call], "shipment": shipment, "evidence": evidence}


def _collect_evidence(
    source: EvidenceSource,
) -> Callable[[InvestigationState], InvestigationState]:
    """Build the graph step that collects one source's evidence."""

    def collect(state: InvestigationState) -> InvestigationState:
        shipment = state["shipment"]
        call, result, error = _run_tool(
            source.tool,
            _tool_input(state),
            lambda: source.collect(shipment),
            source.trace_output,
        )

        if error is None:
            try:
                return {
                    "tool_trace": [call],
                    "evidence": source.summarize(result),
                    "limitations": list(source.success_limitations),
                }
            except Exception as exc:
                error = exc

        reported: Any = error
        if source.public_error is not None:
            logger.warning("%s failed", source.tool, exc_info=error)
            reported = source.public_error
            if call.status == ToolCallStatus.ERROR:
                call = call.model_copy(update={"error": reported})

        if isinstance(error, source.optional_errors):
            return {
                "tool_trace": [call],
                "limitations": [f"{source.limitation}: {reported}"],
            }

        return _failed(error, call)

    return collect


def _generate_briefing(state: InvestigationState) -> InvestigationState:
    """
    Turn the collected evidence into the briefing.

    The evidence comes from tool outputs only: a field no tool provided
    stays empty rather than holding a placeholder value.
    """
    prediction = state["prediction"]
    standing_limitations = [
        WEATHER_SCOPE_LIMITATION,
        *UNCOLLECTED_EVIDENCE_LIMITATIONS,
    ]

    try:
        briefing = generate_rag_briefing(
            shipment_id=prediction.shipment_id,
            risk_level=prediction.risk_level,
            delay_probability=prediction.delay_probability,
            evidence=state["evidence"],
        )
    except Exception as exc:
        return _failed(exc)

    # The briefing reports its own limitations, such as supporting
    # documents that could not be retrieved. They follow the evidence
    # limitations and come before the notes on every briefing.
    briefing_limitations = [*briefing.limitations, *standing_limitations]

    # The trace and limitations are attached here so the briefing
    # service's interface stays unchanged.
    briefing = briefing.model_copy(
        update={
            "tool_trace": state["tool_trace"],
            "limitations": [*state.get("limitations", []), *briefing_limitations],
        }
    )

    return {
        "limitations": briefing_limitations,
        "briefing": briefing,
        "status": InvestigationStatus.COMPLETED,
    }


# ============================================================
# ROUTING
# ============================================================


def _has_failed(state: InvestigationState) -> bool:
    return state.get("status") is InvestigationStatus.FAILED


def _route_on_risk(state: InvestigationState) -> str:
    """ENFORCE THE GATE: only shipments that require it are investigated."""
    if _has_failed(state):
        return END
    if not state["prediction"].requires_investigation:
        return INVESTIGATION_NOT_REQUIRED
    return GET_SHIPMENT


def _continue_to(next_step: str) -> Callable[[InvestigationState], str]:
    """Route to the next step unless the investigation has failed."""

    def route(state: InvestigationState) -> str:
        return END if _has_failed(state) else next_step

    return route


def build_investigation_graph() -> CompiledStateGraph:
    """
    Build the investigation workflow: risk gate, shipment facts, one
    step per entry in EVIDENCE_SOURCES, then the briefing.
    """
    graph = StateGraph(InvestigationState)

    graph.add_node(ASSESS_RISK, _assess_risk)
    graph.add_node(INVESTIGATION_NOT_REQUIRED, _investigation_not_required)
    graph.add_node(GET_SHIPMENT, _get_shipment)
    graph.add_node(GENERATE_BRIEFING, _generate_briefing)

    graph.add_edge(START, ASSESS_RISK)
    graph.add_conditional_edges(
        ASSESS_RISK,
        _route_on_risk,
        [GET_SHIPMENT, INVESTIGATION_NOT_REQUIRED, END],
    )
    graph.add_edge(INVESTIGATION_NOT_REQUIRED, END)

    # Evidence is collected one source at a time so progress events,
    # the trace and the limitations keep a stable order.
    previous = GET_SHIPMENT
    for source in EVIDENCE_SOURCES:
        graph.add_node(source.tool, _collect_evidence(source))
        graph.add_conditional_edges(
            previous,
            _continue_to(source.tool),
            [source.tool, END],
        )
        previous = source.tool

    graph.add_conditional_edges(
        previous,
        _continue_to(GENERATE_BRIEFING),
        [GENERATE_BRIEFING, END],
    )
    graph.add_edge(GENERATE_BRIEFING, END)

    return graph.compile()


INVESTIGATION_GRAPH = build_investigation_graph()

# Steps that are tool calls, and so are reported as progress events:
# the two required tools and every evidence source in the graph.
_TOOL_STEPS = frozenset(
    {ASSESS_RISK, GET_SHIPMENT, *(source.tool for source in EVIDENCE_SOURCES)}
)


# ============================================================
# PUBLIC INTERFACE
# ============================================================


def iter_investigation(
    shipment_id: str,
) -> Generator[InvestigationEvent, None, DisruptionBriefingResponse]:
    """
    Orchestrates the AI Agent investigation. Strictly enforces the Risk Gate:
    only shipments flagged as requiring investigation are processed.

    Flow: risk gate, shipment facts, historical delay context,
    destination weather, inventory record, supplier candidates, briefing. Every tool call is recorded in the response's tool_trace.
    The risk gate and shipment facts are required; other evidence that
    cannot be collected is reported in limitations.

    The workflow itself is INVESTIGATION_GRAPH. This generator runs it
    and reports its progress as events: tool_start when the graph
    announces a tool step, tool_complete or tool_error when the step
    has recorded its call, then message and done with the briefing.

    It yields an event for each step as the step happens and returns
    the finished briefing; the last event, done, carries that briefing
    in JSON form. Each step runs only when the next event is requested,
    so a caller that stops iterating stops the investigation. Fatal
    failures are raised, exactly as run_investigation raises them.
    """
    state: InvestigationState = {}

    # "tasks" announces a step before it runs, "updates" carries what
    # the step returned and "values" is the state after the step.
    steps = INVESTIGATION_GRAPH.stream(
        {"shipment_id": shipment_id},
        stream_mode=["tasks", "updates", "values"],
    )

    # Closing the graph run with this generator means an abandoned
    # investigation is released at once, not when it is collected.
    with closing(steps):
        for mode, payload in steps:
            if mode == "values":
                state = payload

            elif mode == "tasks":
                # A task is reported twice; only the announcement,
                # sent before the step runs, has its input.
                if "input" in payload and payload["name"] in _TOOL_STEPS:
                    yield InvestigationEvent(
                        TOOL_START,
                        {
                            "name": payload["name"],
                            "input": _tool_input(payload["input"]),
                        },
                    )

            else:
                for update in payload.values():
                    for call in (update or {}).get("tool_trace", []):
                        yield _tool_event(
                            TOOL_COMPLETE
                            if call.status == ToolCallStatus.SUCCESS
                            else TOOL_ERROR,
                            call,
                        )

    status = state.get("status")

    if status is InvestigationStatus.FAILED:
        raise state["failure"]

    if status is InvestigationStatus.NOT_REQUIRED:
        prediction = state["prediction"]
        raise InvestigationNotRequiredError(f"Shipment {shipment_id} is LOW risk ({prediction.delay_probability}) and does not require AI investigation.")

    briefing = state["briefing"]

    yield InvestigationEvent(
        MESSAGE,
        {"role": "agent", "content": briefing.summary},
    )
    yield InvestigationEvent(DONE, briefing.model_dump(mode="json"))

    return briefing


def run_investigation(shipment_id: str) -> DisruptionBriefingResponse:
    """
    Run the investigation to completion and return the briefing.

    Drives iter_investigation without reporting its progress events.
    """
    events = iter_investigation(shipment_id)
    while True:
        try:
            next(events)
        except StopIteration as finished:
            return finished.value
