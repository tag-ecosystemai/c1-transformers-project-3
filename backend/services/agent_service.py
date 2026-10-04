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
    PredictionResponse,
    ShipmentResponse,
    ToolCall,
    ToolCallStatus,
    ToolEvidence,
)
from backend.exceptions import (
    InvestigationNotRequiredError,
    WeatherServiceError,
)
from backend.services.agent_tools import (
    get_delay_risk,
    get_destination_weather,
    get_historical_delay_context,
    get_shipment,
)
from backend.services.briefing_service import generate_rag_briefing


# Applies to every briefing, whether or not weather was collected.
WEATHER_SCOPE_LIMITATION = (
    "Weather describes the geocoded destination city over an approximate "
    "window (order date plus scheduled shipping days), not the full "
    "shipment route."
)

# Evidence that this version of the investigation does not collect yet.
UNCOLLECTED_EVIDENCE_LIMITATIONS = [
    "Supplier status was not collected: no supplier data source is available.",
    "Inventory coverage was not collected: no inventory data source is available.",
    "Policy citations and recommended actions come from the briefing "
    "service placeholder: RAG retrieval is not yet integrated.",
]


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
) -> tuple[ToolCall, Any, Exception | None]:
    """
    Run one tool and describe the call for the trace.

    Returns the recorded call, the tool's result and the exception it
    raised, if any. The tool is passed as a zero-argument callable so
    its failure happens here and is recorded; the calling step decides
    whether the investigation can continue. Outputs are stored in JSON
    form so the trace can be returned in the API response.
    """
    try:
        result = function()
    except Exception as exc:
        call = ToolCall(
            tool=tool,
            input=tool_input,
            status=ToolCallStatus.ERROR,
            error=str(exc),
        )
        return call, None, exc

    output = (
        result.model_dump(mode="json")
        if isinstance(result, BaseModel)
        else result
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
        )

        if error is None:
            try:
                return {"tool_trace": [call], "evidence": source.summarize(result)}
            except Exception as exc:
                error = exc

        if isinstance(error, source.optional_errors):
            return {
                "tool_trace": [call],
                "limitations": [f"{source.limitation}: {error}"],
            }

        return _failed(error, call)

    return collect


def _generate_briefing(state: InvestigationState) -> InvestigationState:
    """
    Turn the collected evidence into the briefing.

    The evidence comes from tool outputs only: supplier and inventory
    fields stay empty rather than holding placeholder values.
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

    # The trace and limitations are attached here so the briefing
    # service's interface stays unchanged.
    briefing = briefing.model_copy(
        update={
            "tool_trace": state["tool_trace"],
            "limitations": [*state.get("limitations", []), *standing_limitations],
        }
    )

    return {
        "limitations": standing_limitations,
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
    destination weather, evidence, briefing. Every tool call is recorded in the response's tool_trace.
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
