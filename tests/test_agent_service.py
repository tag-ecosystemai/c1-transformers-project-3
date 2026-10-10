import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import routes_agent
from backend.exceptions import WeatherServiceError
from backend.models.schemas import (
    DisruptionBriefingResponse,
    RiskLevel,
    ToolCallStatus,
)
from backend.services import agent_service
from backend.services.agent_service import (
    INVENTORY_SCOPE_LIMITATION,
    UNCOLLECTED_EVIDENCE_LIMITATIONS,
    WEATHER_SCOPE_LIMITATION,
    run_investigation,
)
from backend.services.shipment_service import ShipmentNotFoundError


EXPECTED_TOOLS = [
    "get_delay_risk",
    "get_shipment",
    "get_historical_delay_context",
    "get_destination_weather",
    "get_inventory_coverage",
]

# The inventory step runs last, so the note on its record follows any
# failure and comes before the notes that apply to every briefing.
STANDING_LIMITATIONS = [
    INVENTORY_SCOPE_LIMITATION,
    WEATHER_SCOPE_LIMITATION,
    *UNCOLLECTED_EVIDENCE_LIMITATIONS,
]


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes_agent.router)
    return TestClient(app)


# ============================================================
# SERVICE
# ============================================================


def test_successful_investigation_returns_briefing(high_risk):
    briefing = run_investigation("SHP-153440")

    assert isinstance(briefing, DisruptionBriefingResponse)
    assert briefing.shipment_id == "SHP-153440"
    assert briefing.risk_level == RiskLevel.HIGH
    assert briefing.delay_probability == 0.82
    assert briefing.evidence.shipment_summary == (
        "SHP-153440: 2 x Trail Running Shoe (Cleats) to Vassouras, "
        "Brasil by Standard Class, scheduled for 4 days, ordered "
        "2017-05-01."
    )
    assert briefing.evidence.historical_delay_summary == (
        "Historical delay rates: product 57.0%, market 55.0%, "
        "shipping mode 38.0%. Highest: product."
    )


def test_investigation_does_not_invent_uncollected_evidence(high_risk):
    evidence = run_investigation("SHP-153440").evidence

    assert evidence.supplier_status is None
    assert evidence.inventory_coverage_days is None


def test_tool_trace_records_each_call_in_order(high_risk):
    trace = run_investigation("SHP-153440").tool_trace

    assert [call.tool for call in trace] == EXPECTED_TOOLS
    assert all(call.status == ToolCallStatus.SUCCESS for call in trace)
    assert all(
        call.input == {"shipment_id": "SHP-153440"} for call in trace
    )
    assert trace[0].output == high_risk.model_dump(mode="json")
    assert trace[1].output["shipment_reference"] == "SHP-153440"
    assert trace[2].output["highest_delay_rate_factor"] == "product"
    assert trace[3].output["source"] == "Open-Meteo historical archive"
    assert trace[4].output["inventory_coverage_days"] == 17.13


def test_limitations_list_uncollected_evidence(high_risk):
    briefing = run_investigation("SHP-153440")

    assert briefing.limitations == STANDING_LIMITATIONS


def test_weather_step_populates_weather_evidence(high_risk):
    briefing = run_investigation("SHP-153440")

    assert briefing.evidence.weather_summary == (
        "Observed weather in Vassouras, Brazil, 2017-05-01 to 2017-05-05: "
        "9.2 mm precipitation (max 8.9 mm/day), max wind 17.9 km/h; "
        "worst condition slight rain (low severity)."
    )
    assert "environmental evidence: Observed weather" in briefing.summary


def test_weather_failure_becomes_limitation(high_risk, monkeypatch):
    def weather_unavailable(shipment):
        raise WeatherServiceError("Open-Meteo did not respond within 10 seconds.")

    monkeypatch.setattr(
        agent_service,
        "get_destination_weather",
        weather_unavailable,
    )

    briefing = run_investigation("SHP-153440")

    failed_call = briefing.tool_trace[3]
    assert failed_call.tool == "get_destination_weather"
    assert failed_call.status == ToolCallStatus.ERROR
    assert failed_call.error == "Open-Meteo did not respond within 10 seconds."

    assert briefing.evidence.weather_summary is None
    assert briefing.limitations == [
        "Weather evidence was not collected: "
        "Open-Meteo did not respond within 10 seconds.",
        *STANDING_LIMITATIONS,
    ]


def test_risk_gate_rejects_low_risk_shipment(low_risk, monkeypatch):
    def fail_if_called(shipment_id):
        raise AssertionError("shipment tool must not run after rejection")

    monkeypatch.setattr(agent_service, "get_shipment", fail_if_called)

    with pytest.raises(ValueError, match="LOW risk"):
        run_investigation("SHP-153440")


def test_unknown_shipment_raises_not_found(shipment_data, monkeypatch):
    def not_found(shipment_id):
        raise ShipmentNotFoundError(f"Shipment '{shipment_id}' was not found.")

    monkeypatch.setattr(agent_service, "get_delay_risk", not_found)

    with pytest.raises(ShipmentNotFoundError):
        run_investigation("SHP-999999")


def test_optional_tool_failure_becomes_limitation(high_risk, monkeypatch):
    def broken_context(shipment):
        raise RuntimeError("context source unavailable")

    monkeypatch.setattr(
        agent_service,
        "get_historical_delay_context",
        broken_context,
    )

    briefing = run_investigation("SHP-153440")

    failed_call = briefing.tool_trace[2]
    assert failed_call.tool == "get_historical_delay_context"
    assert failed_call.status == ToolCallStatus.ERROR
    assert failed_call.output is None
    assert failed_call.error == "context source unavailable"

    assert briefing.evidence.historical_delay_summary is None
    assert briefing.limitations[0] == (
        "Historical delay context was not collected: "
        "context source unavailable"
    )


def test_required_tool_failure_stops_investigation(high_risk, monkeypatch):
    def broken_shipment(shipment_id):
        raise RuntimeError("shipment data unavailable")

    monkeypatch.setattr(agent_service, "get_shipment", broken_shipment)

    with pytest.raises(RuntimeError, match="shipment data unavailable"):
        run_investigation("SHP-153440")


# ============================================================
# API
# ============================================================


def test_investigate_endpoint_returns_briefing_schema(client, high_risk):
    response = client.post("/api/agent/investigate/SHP-153440")

    assert response.status_code == 200
    body = response.json()
    DisruptionBriefingResponse.model_validate(body)
    assert body["risk_level"] == "HIGH"
    assert [call["tool"] for call in body["tool_trace"]] == EXPECTED_TOOLS
    assert body["tool_trace"][0]["status"] == "success"
    assert body["limitations"] == STANDING_LIMITATIONS


def test_investigate_endpoint_rejects_low_risk(client, low_risk):
    response = client.post("/api/agent/investigate/SHP-153440")

    assert response.status_code == 400
    assert "LOW risk" in response.json()["detail"]


def test_investigate_endpoint_unknown_shipment_returns_404(
    client,
    shipment_data,
    monkeypatch,
):
    def not_found(shipment_id):
        raise ShipmentNotFoundError(f"Shipment '{shipment_id}' was not found.")

    monkeypatch.setattr(agent_service, "get_delay_risk", not_found)

    response = client.post("/api/agent/investigate/SHP-999999")

    assert response.status_code == 404
    assert "was not found" in response.json()["detail"]
