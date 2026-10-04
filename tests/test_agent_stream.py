import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import routes_agent
from backend.exceptions import WeatherServiceError
from backend.models.schemas import DisruptionBriefingResponse
from backend.services import agent_service
from backend.services.agent_service import (
    UNCOLLECTED_EVIDENCE_LIMITATIONS,
    WEATHER_SCOPE_LIMITATION,
    iter_investigation,
    run_investigation,
)
from backend.services.shipment_service import (
    InvalidShipmentReferenceError,
    ShipmentNotFoundError,
)


STREAM_URL = "/api/agent/investigate/SHP-153440/stream"

EXPECTED_TOOLS = [
    "get_delay_risk",
    "get_shipment",
    "get_historical_delay_context",
    "get_destination_weather",
]

STANDING_LIMITATIONS = [
    WEATHER_SCOPE_LIMITATION,
    *UNCOLLECTED_EVIDENCE_LIMITATIONS,
]

TERMINAL_EVENTS = {"done", "error"}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes_agent.router)
    return TestClient(app)


def parse_sse(text: str) -> list[tuple[str, dict]]:
    """
    Parse a Server-Sent Events body strictly: every block must be one
    event line followed by one JSON data line.
    """
    assert text.endswith("\n\n"), "the last event was not terminated"

    events = []
    for block in text.split("\n\n")[:-1]:
        lines = block.split("\n")
        assert len(lines) == 2, f"unexpected event framing: {block!r}"
        assert lines[0].startswith("event: ")
        assert lines[1].startswith("data: ")
        events.append(
            (
                lines[0].removeprefix("event: "),
                json.loads(lines[1].removeprefix("data: ")),
            )
        )
    return events


def stream(client, url: str = STREAM_URL) -> list[tuple[str, dict]]:
    response = client.get(url)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


def names(events: list[tuple[str, dict]]) -> list[str]:
    return [name for name, _ in events]


def assert_single_terminal_event(events: list[tuple[str, dict]]) -> None:
    terminal = [name for name in names(events) if name in TERMINAL_EVENTS]

    assert len(terminal) == 1
    assert events[-1][0] == terminal[0]


def forbid(monkeypatch, tool: str) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError(f"{tool} must not run")

    monkeypatch.setattr(agent_service, tool, fail_if_called)


# ============================================================
# SUCCESSFUL STREAM
# ============================================================


def test_stream_reports_every_tool_in_order(client, high_risk):
    events = stream(client)

    expected = []
    for tool in EXPECTED_TOOLS:
        expected += [("tool_start", tool), ("tool_complete", tool)]
    tool_events = [
        (name, data["name"])
        for name, data in events
        if name.startswith("tool_")
    ]

    assert tool_events == expected
    assert names(events)[-2:] == ["message", "done"]
    assert_single_terminal_event(events)


def test_stream_sets_sse_headers(client, high_risk):
    response = client.get(STREAM_URL)

    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"


def test_tool_events_carry_the_recorded_tool_calls(client, high_risk):
    events = stream(client)

    starts = [data for name, data in events if name == "tool_start"]
    completed = [data for name, data in events if name == "tool_complete"]
    trace = events[-1][1]["tool_trace"]

    assert all(
        start == {"name": tool, "input": {"shipment_id": "SHP-153440"}}
        for start, tool in zip(starts, EXPECTED_TOOLS)
    )
    # A tool_complete event is the trace entry with the tool under "name".
    assert [
        {"tool": data["name"], **{k: v for k, v in data.items() if k != "name"}}
        for data in completed
    ] == trace
    assert completed[0]["output"] == high_risk.model_dump(mode="json")
    assert all(data["status"] == "success" for data in completed)


def test_message_event_carries_the_briefing_summary(client, high_risk):
    events = stream(client)
    message = events[-2][1]

    assert message == {"role": "agent", "content": events[-1][1]["summary"]}


def test_done_payload_matches_synchronous_response(client, high_risk):
    done = stream(client)[-1][1]
    synchronous = client.post("/api/agent/investigate/SHP-153440").json()

    assert done == synchronous
    DisruptionBriefingResponse.model_validate(done)
    assert set(done) == {
        "shipment_id",
        "risk_level",
        "delay_probability",
        "evidence",
        "rag_policy_citations",
        "summary",
        "recommended_actions",
        "tool_trace",
        "limitations",
    }
    assert done["shipment_id"] == "SHP-153440"
    assert done["risk_level"] == "HIGH"
    assert done["delay_probability"] == 0.82
    assert done["limitations"] == STANDING_LIMITATIONS


# ============================================================
# OPTIONAL TOOL FAILURES
# ============================================================


def test_weather_failure_emits_tool_error_and_continues(
    client,
    high_risk,
    monkeypatch,
):
    def weather_unavailable(shipment):
        raise WeatherServiceError("Open-Meteo did not respond within 10 seconds.")

    monkeypatch.setattr(
        agent_service,
        "get_destination_weather",
        weather_unavailable,
    )

    events = stream(client)

    assert ("tool_error", {
        "name": "get_destination_weather",
        "input": {"shipment_id": "SHP-153440"},
        "output": None,
        "status": "error",
        "error": "Open-Meteo did not respond within 10 seconds.",
    }) in events
    assert "tool_complete" not in [
        name for name, data in events
        if data.get("name") == "get_destination_weather"
    ]
    assert_single_terminal_event(events)

    name, done = events[-1]
    assert name == "done"
    assert done["evidence"]["weather_summary"] is None
    assert done["tool_trace"][-1]["status"] == "error"
    assert done["limitations"] == [
        "Weather evidence was not collected: "
        "Open-Meteo did not respond within 10 seconds.",
        *STANDING_LIMITATIONS,
    ]


def test_historical_context_failure_emits_tool_error_and_continues(
    client,
    high_risk,
    monkeypatch,
):
    def broken_context(shipment):
        raise RuntimeError("context source unavailable")

    monkeypatch.setattr(
        agent_service,
        "get_historical_delay_context",
        broken_context,
    )

    events = stream(client)

    # The failure is reported, then the weather tool still runs.
    assert [
        (name, data["name"])
        for name, data in events
        if name.startswith("tool_")
    ][4:] == [
        ("tool_start", "get_historical_delay_context"),
        ("tool_error", "get_historical_delay_context"),
        ("tool_start", "get_destination_weather"),
        ("tool_complete", "get_destination_weather"),
    ]

    name, done = events[-1]
    assert name == "done"
    assert done["evidence"]["historical_delay_summary"] is None
    assert done["evidence"]["weather_summary"] is not None
    assert done["limitations"][0] == (
        "Historical delay context was not collected: "
        "context source unavailable"
    )


# ============================================================
# FATAL ERRORS
# ============================================================


def test_low_risk_shipment_ends_with_not_required_error(
    client,
    low_risk,
    monkeypatch,
):
    forbid(monkeypatch, "get_shipment")

    events = stream(client)

    # The risk tool itself succeeded; the gate then rejected the shipment.
    assert names(events) == ["tool_start", "tool_complete", "error"]
    assert events[1][1]["output"]["requires_investigation"] is False

    error = events[-1][1]
    assert error["status"] == 400
    assert error["code"] == "investigation_not_required"
    assert "LOW risk" in error["detail"]


def test_unknown_shipment_ends_with_not_found_error(
    client,
    shipment_data,
    monkeypatch,
):
    def not_found(shipment_id):
        raise ShipmentNotFoundError(f"Shipment '{shipment_id}' was not found.")

    monkeypatch.setattr(agent_service, "get_delay_risk", not_found)

    events = stream(client, "/api/agent/investigate/SHP-999999/stream")

    assert names(events) == ["tool_start", "tool_error", "error"]
    assert events[-1][1] == {
        "status": 404,
        "code": "shipment_not_found",
        "detail": "Shipment 'SHP-999999' was not found.",
    }


def test_invalid_reference_is_not_reported_as_low_risk(
    client,
    shipment_data,
    monkeypatch,
):
    def invalid(shipment_id):
        raise InvalidShipmentReferenceError("Invalid shipment reference.")

    monkeypatch.setattr(agent_service, "get_delay_risk", invalid)

    error = stream(client, "/api/agent/investigate/nonsense/stream")[-1]

    assert error == ("error", {
        "status": 400,
        "code": "invalid_request",
        "detail": "Invalid shipment reference.",
    })


def test_required_tool_failure_ends_stream_with_error(
    client,
    high_risk,
    monkeypatch,
):
    def broken_shipment(shipment_id):
        raise RuntimeError("shipment data unavailable")

    monkeypatch.setattr(agent_service, "get_shipment", broken_shipment)
    forbid(monkeypatch, "get_historical_delay_context")
    forbid(monkeypatch, "get_destination_weather")

    events = stream(client)

    assert names(events) == [
        "tool_start",
        "tool_complete",
        "tool_start",
        "tool_error",
        "error",
    ]
    assert events[3][1]["name"] == "get_shipment"
    assert events[-1][1] == {
        "status": 500,
        "code": "investigation_failed",
        "detail": "Agent investigation failed: shipment data unavailable",
    }
    assert_single_terminal_event(events)


def test_briefing_failure_ends_stream_with_error(
    client,
    high_risk,
    monkeypatch,
):
    def broken_briefing(**kwargs):
        raise RuntimeError("briefing model unavailable")

    monkeypatch.setattr(agent_service, "generate_rag_briefing", broken_briefing)

    events = stream(client)

    # Every tool succeeded, but without a briefing there is no done event.
    assert names(events).count("tool_complete") == 4
    assert "tool_error" not in names(events)
    assert "done" not in names(events)
    assert events[-1][1]["status"] == 500
    assert events[-1][1]["code"] == "investigation_failed"


def test_error_event_matches_synchronous_error(client, low_risk):
    error = stream(client)[-1][1]
    response = client.post("/api/agent/investigate/SHP-153440")

    assert response.status_code == error["status"]
    assert response.json()["detail"] == error["detail"]


def test_multiline_error_does_not_break_event_framing(
    client,
    high_risk,
    monkeypatch,
):
    def broken_shipment(shipment_id):
        raise RuntimeError("line one\n\ndata: forged\r\nline three")

    monkeypatch.setattr(agent_service, "get_shipment", broken_shipment)

    # parse_sse rejects any block that is not one event and one data line.
    events = stream(client)

    assert events[-1][0] == "error"
    assert events[-1][1]["detail"].endswith(
        "line one\n\ndata: forged\r\nline three"
    )


# ============================================================
# DISCONNECTS AND SHARED EXECUTION
# ============================================================


def test_closed_stream_stops_calling_tools(high_risk, monkeypatch):
    forbid(monkeypatch, "get_shipment")
    closed = []
    real_iter_investigation = routes_agent.iter_investigation

    def tracked(shipment_id):
        try:
            yield from real_iter_investigation(shipment_id)
        finally:
            closed.append(shipment_id)

    monkeypatch.setattr(routes_agent, "iter_investigation", tracked)

    async def disconnect_after_risk_result():
        body = routes_agent._event_stream("SHP-153440")
        received = [await anext(body), await anext(body)]
        # What Starlette does to the response body when the client goes away.
        await body.aclose()
        return received

    received = asyncio.run(disconnect_after_risk_result())

    assert [chunk.split("\n")[0] for chunk in received] == [
        "event: tool_start",
        "event: tool_complete",
    ]
    assert closed == ["SHP-153440"]


def test_abandoned_investigation_runs_no_further_tools(high_risk, monkeypatch):
    forbid(monkeypatch, "get_shipment")

    events = iter_investigation("SHP-153440")
    assert next(events).event == "tool_start"
    assert next(events).event == "tool_complete"
    events.close()

    with pytest.raises(StopIteration):
        next(events)


def record_tool_executions(monkeypatch, log: list) -> None:
    """
    Wrap every tool so that the moment it actually executes is appended
    to the same log as the events the consumer receives.
    """
    for tool in EXPECTED_TOOLS:
        original = getattr(agent_service, tool)

        def recorded(*args, _tool=tool, _original=original, **kwargs):
            log.append(("executes", _tool))
            return _original(*args, **kwargs)

        monkeypatch.setattr(agent_service, tool, recorded)


def test_tool_start_is_received_before_the_tool_executes(
    high_risk,
    monkeypatch,
):
    log = []
    record_tool_executions(monkeypatch, log)

    for event in iter_investigation("SHP-153440"):
        log.append((event.event, event.data.get("name")))

    # Each tool runs only after its tool_start reached the consumer, and
    # no tool runs ahead of the events that precede it.
    expected = []
    for tool in EXPECTED_TOOLS:
        expected += [
            ("tool_start", tool),
            ("executes", tool),
            ("tool_complete", tool),
        ]
    assert log[:-2] == expected
    assert [name for name, _ in log[-2:]] == ["message", "done"]


def test_consumer_stopping_after_first_event_runs_no_tool(
    high_risk,
    monkeypatch,
):
    log = []
    record_tool_executions(monkeypatch, log)

    events = iter_investigation("SHP-153440")
    assert next(events).event == "tool_start"
    events.close()

    assert log == []


def test_both_optional_failures_keep_order_and_match_synchronous_response(
    client,
    high_risk,
    monkeypatch,
):
    def broken_context(shipment):
        raise RuntimeError("context source unavailable")

    def weather_unavailable(shipment):
        raise WeatherServiceError("Open-Meteo request failed.")

    monkeypatch.setattr(
        agent_service,
        "get_historical_delay_context",
        broken_context,
    )
    monkeypatch.setattr(
        agent_service,
        "get_destination_weather",
        weather_unavailable,
    )

    events = stream(client)
    name, done = events[-1]

    assert name == "done"
    assert [
        (name, data["name"])
        for name, data in events
        if name.startswith("tool_")
    ][4:] == [
        ("tool_start", "get_historical_delay_context"),
        ("tool_error", "get_historical_delay_context"),
        ("tool_start", "get_destination_weather"),
        ("tool_error", "get_destination_weather"),
    ]
    assert [(call["tool"], call["status"]) for call in done["tool_trace"]] == [
        ("get_delay_risk", "success"),
        ("get_shipment", "success"),
        ("get_historical_delay_context", "error"),
        ("get_destination_weather", "error"),
    ]
    # Failures first, in the order the tools ran, then the standing notes.
    assert done["limitations"] == [
        "Historical delay context was not collected: "
        "context source unavailable",
        "Weather evidence was not collected: Open-Meteo request failed.",
        *STANDING_LIMITATIONS,
    ]
    assert done["evidence"]["historical_delay_summary"] is None
    assert done["evidence"]["weather_summary"] is None
    assert done == client.post("/api/agent/investigate/SHP-153440").json()


def test_synchronous_run_returns_the_streamed_briefing(high_risk):
    streamed = list(iter_investigation("SHP-153440"))

    assert streamed[-1].event == "done"
    assert streamed[-1].data == run_investigation("SHP-153440").model_dump(
        mode="json"
    )


def test_application_registers_stream_route():
    from backend.main import app

    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert "get" in paths["/api/agent/investigate/{shipment_id}/stream"]
    assert "post" in paths["/api/agent/investigate/{shipment_id}"]
