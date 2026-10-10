import pytest

from backend.exceptions import (
    InvestigationNotRequiredError,
    WeatherServiceError,
)
from backend.models.schemas import (
    DisruptionBriefingResponse,
    PredictionResponse,
    RiskLevel,
    ToolCallStatus,
    ToolEvidence,
)
from backend.services import agent_service, agent_tools
from backend.services.agent_service import (
    EVIDENCE_SOURCES,
    INVESTIGATION_GRAPH,
    INVENTORY_SCOPE_LIMITATION,
    SUPPLIER_SCOPE_LIMITATION,
    UNCOLLECTED_EVIDENCE_LIMITATIONS,
    WEATHER_SCOPE_LIMITATION,
    EvidenceSource,
    InvestigationStatus,
    build_investigation_graph,
    iter_investigation,
    run_investigation,
)
from backend.services.shipment_service import ShipmentNotFoundError


EXPECTED_TOOLS = [
    "get_delay_risk",
    "get_shipment",
    "get_historical_delay_context",
    "get_destination_weather",
    "get_inventory_coverage",
    "find_alternative_supplier",
]

# The inventory and supplier steps run last, so the notes on what they
# collected follow any failure and come before the notes that apply to
# every briefing.
STANDING_LIMITATIONS = [
    INVENTORY_SCOPE_LIMITATION,
    SUPPLIER_SCOPE_LIMITATION,
    WEATHER_SCOPE_LIMITATION,
    *UNCOLLECTED_EVIDENCE_LIMITATIONS,
]


def use_prediction(
    monkeypatch,
    risk_level: RiskLevel,
    probability: float,
    requires_investigation: bool,
) -> PredictionResponse:
    """Make the model return a chosen risk decision."""
    prediction = PredictionResponse(
        shipment_id="SHP-153440",
        delay_probability=probability,
        risk_level=risk_level,
        requires_investigation=requires_investigation,
    )
    monkeypatch.setattr(
        agent_tools,
        "predict_delay_risk",
        lambda shipment_id: prediction,
    )
    return prediction


def investigate(shipment_id: str = "SHP-153440") -> dict:
    """Run the graph itself and return the final investigation state."""
    return INVESTIGATION_GRAPH.invoke({"shipment_id": shipment_id})


def traced(state: dict) -> list[tuple[str, ToolCallStatus]]:
    return [(call.tool, call.status) for call in state["tool_trace"]]


def forbid(monkeypatch, *tools: str) -> None:
    for tool in tools:

        def fail_if_called(*args, _tool=tool, **kwargs):
            raise AssertionError(f"{_tool} must not run")

        monkeypatch.setattr(agent_service, tool, fail_if_called)


# ============================================================
# STRUCTURE
# ============================================================


def test_graph_has_one_step_per_tool_plus_gate_and_briefing():
    nodes = set(INVESTIGATION_GRAPH.get_graph().nodes) - {"__start__", "__end__"}

    assert nodes == {
        *EXPECTED_TOOLS,
        "investigation_not_required",
        "generate_briefing",
    }


def test_graph_routes_are_explicit():
    edges = {
        (edge.source, edge.target)
        for edge in INVESTIGATION_GRAPH.get_graph().edges
    }

    assert edges == {
        ("__start__", "get_delay_risk"),
        # The risk gate.
        ("get_delay_risk", "get_shipment"),
        ("get_delay_risk", "investigation_not_required"),
        ("get_delay_risk", "__end__"),
        ("investigation_not_required", "__end__"),
        # Each step continues, or ends the investigation on failure.
        ("get_shipment", "get_historical_delay_context"),
        ("get_shipment", "__end__"),
        ("get_historical_delay_context", "get_destination_weather"),
        ("get_historical_delay_context", "__end__"),
        ("get_destination_weather", "get_inventory_coverage"),
        ("get_destination_weather", "__end__"),
        ("get_inventory_coverage", "find_alternative_supplier"),
        ("get_inventory_coverage", "__end__"),
        ("find_alternative_supplier", "generate_briefing"),
        ("find_alternative_supplier", "__end__"),
        ("generate_briefing", "__end__"),
    }


def test_investigation_runs_through_the_graph(high_risk, monkeypatch):
    runs = []

    class RecordingGraph:
        def stream(self, *args, **kwargs):
            runs.append((args, kwargs))
            return INVESTIGATION_GRAPH.stream(*args, **kwargs)

    monkeypatch.setattr(agent_service, "INVESTIGATION_GRAPH", RecordingGraph())

    briefing = run_investigation("SHP-153440")

    assert isinstance(briefing, DisruptionBriefingResponse)
    assert [args for args, _ in runs] == [({"shipment_id": "SHP-153440"},)]


# ============================================================
# RISK ROUTING
# ============================================================


def test_low_risk_routes_to_not_required_and_stops(low_risk, monkeypatch):
    forbid(
        monkeypatch,
        "get_shipment",
        "get_historical_delay_context",
        "get_destination_weather",
        "get_inventory_coverage",
        "get_alternative_suppliers",
        "generate_rag_briefing",
    )

    state = investigate()

    assert state["status"] is InvestigationStatus.NOT_REQUIRED
    assert state["prediction"] == low_risk
    assert traced(state) == [("get_delay_risk", ToolCallStatus.SUCCESS)]
    assert "briefing" not in state
    assert "failure" not in state


def test_low_risk_is_reported_to_callers_as_not_required(low_risk):
    with pytest.raises(InvestigationNotRequiredError) as raised:
        run_investigation("SHP-153440")

    assert str(raised.value) == (
        "Shipment SHP-153440 is LOW risk (0.12) and does not require "
        "AI investigation."
    )


@pytest.mark.parametrize(
    ("risk_level", "probability"),
    [(RiskLevel.MEDIUM, 0.55), (RiskLevel.HIGH, 0.82)],
)
def test_elevated_risk_routes_through_the_full_investigation(
    shipment_data,
    monkeypatch,
    risk_level,
    probability,
):
    use_prediction(monkeypatch, risk_level, probability, True)

    state = investigate()

    assert state["status"] is InvestigationStatus.COMPLETED
    assert traced(state) == [
        (tool, ToolCallStatus.SUCCESS) for tool in EXPECTED_TOOLS
    ]
    assert state["briefing"].risk_level == risk_level
    assert state["briefing"].delay_probability == probability


def test_routing_follows_the_risk_gate_decision_not_the_risk_level(
    shipment_data,
    monkeypatch,
):
    # The prediction service owns the rule; the graph only routes on it.
    use_prediction(monkeypatch, RiskLevel.MEDIUM, 0.55, False)

    assert investigate()["status"] is InvestigationStatus.NOT_REQUIRED


# ============================================================
# SHIPMENT AND EVIDENCE
# ============================================================


def test_shipment_lookup_populates_state_and_evidence(high_risk):
    state = investigate()

    assert state["shipment"].shipment_reference == "SHP-153440"
    assert state["evidence"].shipment_summary.startswith(
        "SHP-153440: 2 x Trail Running Shoe (Cleats) to Vassouras, Brasil"
    )


def test_later_steps_use_the_normalized_shipment_reference(
    high_risk,
    monkeypatch,
):
    looked_up = []
    real_get_shipment = agent_service.get_shipment

    def recording_get_shipment(shipment_id):
        looked_up.append(shipment_id)
        return real_get_shipment(shipment_id)

    monkeypatch.setattr(agent_service, "get_shipment", recording_get_shipment)

    starts = [
        event.data["input"]
        for event in iter_investigation(" shp-153440")
        if event.event == "tool_start"
    ]

    # The caller's text reaches the risk tool; everything after it uses
    # the reference the prediction returned.
    assert starts == [
        {"shipment_id": " shp-153440"},
        *[{"shipment_id": "SHP-153440"}] * 5,
    ]
    assert looked_up == ["SHP-153440"]


def test_evidence_from_every_source_is_merged_into_state(high_risk):
    state = investigate()

    assert state["evidence"] == state["briefing"].evidence
    assert state["evidence"].historical_delay_summary == (
        "Historical delay rates: product 57.0%, market 55.0%, "
        "shipping mode 38.0%. Highest: product."
    )
    assert state["evidence"].weather_summary.startswith(
        "Observed weather in Vassouras, Brazil"
    )
    assert state["evidence"].inventory_summary.startswith(
        "Inventory record for 'Trail Running Shoe'"
    )
    assert state["evidence"].supplier_status.startswith(
        "Alternative supplier candidate for product category 'Cleats'"
    )
    assert state["limitations"] == STANDING_LIMITATIONS
    assert state["briefing"].limitations == state["limitations"]
    assert state["briefing"].tool_trace == state["tool_trace"]


def test_optional_evidence_failure_continues_with_a_limitation(
    high_risk,
    monkeypatch,
):
    def weather_unavailable(shipment):
        raise WeatherServiceError("Open-Meteo request failed.")

    monkeypatch.setattr(
        agent_service,
        "get_destination_weather",
        weather_unavailable,
    )

    state = investigate()

    assert state["status"] is InvestigationStatus.COMPLETED
    assert traced(state)[3] == ("get_destination_weather", ToolCallStatus.ERROR)
    assert state["evidence"].weather_summary is None
    assert state["evidence"].historical_delay_summary is not None
    assert state["limitations"] == [
        "Weather evidence was not collected: Open-Meteo request failed.",
        *STANDING_LIMITATIONS,
    ]


def test_evidence_that_cannot_be_summarized_becomes_a_limitation(
    high_risk,
    monkeypatch,
):
    monkeypatch.setattr(
        agent_service,
        "get_historical_delay_context",
        lambda shipment: {"unexpected": "shape"},
    )

    state = investigate()

    # The tool itself answered, so the trace records a successful call.
    assert traced(state)[2] == (
        "get_historical_delay_context",
        ToolCallStatus.SUCCESS,
    )
    assert state["status"] is InvestigationStatus.COMPLETED
    assert state["evidence"].historical_delay_summary is None
    assert state["limitations"][0].startswith(
        "Historical delay context was not collected:"
    )


# ============================================================
# FATAL FAILURES
# ============================================================


def test_unknown_shipment_fails_at_the_risk_step(shipment_data, monkeypatch):
    error = ShipmentNotFoundError("Shipment 'SHP-999999' was not found.")

    def not_found(shipment_id):
        raise error

    monkeypatch.setattr(agent_service, "get_delay_risk", not_found)
    forbid(monkeypatch, "get_shipment")

    state = investigate("SHP-999999")

    assert state["status"] is InvestigationStatus.FAILED
    assert state["failure"] is error
    assert traced(state) == [("get_delay_risk", ToolCallStatus.ERROR)]


def test_required_step_failure_ends_the_investigation(high_risk, monkeypatch):
    error = RuntimeError("shipment data unavailable")

    def broken_shipment(shipment_id):
        raise error

    monkeypatch.setattr(agent_service, "get_shipment", broken_shipment)
    forbid(
        monkeypatch,
        "get_historical_delay_context",
        "get_destination_weather",
        "get_inventory_coverage",
        "get_alternative_suppliers",
        "generate_rag_briefing",
    )

    state = investigate()

    assert state["status"] is InvestigationStatus.FAILED
    assert state["failure"] is error
    assert traced(state) == [
        ("get_delay_risk", ToolCallStatus.SUCCESS),
        ("get_shipment", ToolCallStatus.ERROR),
    ]
    assert "briefing" not in state


def test_shipment_summary_defect_fails_after_reporting_the_tool_call(
    high_risk,
    monkeypatch,
):
    error = TypeError("summary defect")

    def defective_summary(shipment):
        raise error

    monkeypatch.setattr(agent_service, "_summarize_shipment", defective_summary)
    forbid(monkeypatch, "generate_rag_briefing")

    events = []
    with pytest.raises(TypeError) as raised:
        for event in iter_investigation("SHP-153440"):
            events.append((event.event, event.data["name"]))

    # The shipment tool did answer, so its call is still reported
    # before the investigation fails with the original exception.
    assert raised.value is error
    assert events[-2:] == [
        ("tool_start", "get_shipment"),
        ("tool_complete", "get_shipment"),
    ]

    state = investigate()
    assert state["status"] is InvestigationStatus.FAILED
    assert state["failure"] is error
    assert traced(state)[-1] == ("get_shipment", ToolCallStatus.SUCCESS)


def test_unexpected_weather_failure_is_fatal_not_a_limitation(
    high_risk,
    monkeypatch,
):
    # Only the weather service's own error is optional.
    error = KeyError("daily")

    def defective_weather(shipment):
        raise error

    monkeypatch.setattr(
        agent_service,
        "get_destination_weather",
        defective_weather,
    )
    forbid(
        monkeypatch,
        "get_inventory_coverage",
        "get_alternative_suppliers",
        "generate_rag_briefing",
    )

    state = investigate()

    assert state["status"] is InvestigationStatus.FAILED
    assert state["failure"] is error
    assert traced(state)[-1] == ("get_destination_weather", ToolCallStatus.ERROR)
    assert state.get("limitations", []) == []


def test_briefing_failure_ends_the_investigation(high_risk, monkeypatch):
    error = RuntimeError("briefing model unavailable")

    def broken_briefing(**kwargs):
        raise error

    monkeypatch.setattr(agent_service, "generate_rag_briefing", broken_briefing)

    state = investigate()

    assert state["status"] is InvestigationStatus.FAILED
    assert state["failure"] is error
    assert len(state["tool_trace"]) == 6
    assert "briefing" not in state


def test_callers_receive_the_original_exception(high_risk, monkeypatch):
    error = RuntimeError("shipment data unavailable")

    def broken_shipment(shipment_id):
        raise error

    monkeypatch.setattr(agent_service, "get_shipment", broken_shipment)

    with pytest.raises(RuntimeError) as raised:
        run_investigation("SHP-153440")

    # The same object the tool raised: nothing wraps or replaces it.
    assert raised.value is error


# ============================================================
# STREAMING THROUGH THE GRAPH
# ============================================================


def test_abandoning_the_investigation_releases_the_graph_run(
    high_risk,
    monkeypatch,
):
    closed = []

    class TrackingGraph:
        def stream(self, *args, **kwargs):
            steps = INVESTIGATION_GRAPH.stream(*args, **kwargs)
            try:
                yield from steps
            finally:
                closed.append(True)

    monkeypatch.setattr(agent_service, "INVESTIGATION_GRAPH", TrackingGraph())
    forbid(monkeypatch, "get_shipment")

    events = iter_investigation("SHP-153440")
    next(events)
    next(events)
    assert closed == []

    events.close()

    assert closed == [True]


# ============================================================
# EXTENDING THE INVESTIGATION
# ============================================================


def test_a_new_evidence_source_only_needs_to_be_registered(
    high_risk,
    monkeypatch,
):
    whole_days = EvidenceSource(
        tool="get_whole_day_coverage",
        collect=lambda shipment: {"days": 12},
        summarize=lambda result: ToolEvidence(
            inventory_coverage_days=result["days"]
        ),
        limitation="Whole-day coverage was not collected",
        optional_errors=(Exception,),
    )
    monkeypatch.setattr(
        agent_service,
        "EVIDENCE_SOURCES",
        (*EVIDENCE_SOURCES, whole_days),
    )

    state = build_investigation_graph().invoke({"shipment_id": "SHP-153440"})

    assert [call.tool for call in state["tool_trace"]] == [
        *EXPECTED_TOOLS,
        "get_whole_day_coverage",
    ]
    assert state["status"] is InvestigationStatus.COMPLETED
    # The new evidence reaches the briefing with the rest.
    assert state["briefing"].evidence.inventory_coverage_days == 12
    assert state["briefing"].evidence.weather_summary is not None
