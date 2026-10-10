"""
Inventory as an optional evidence source in the investigation.

The inventory record is product-level: it is reported without the
warehouse, supplier, reorder point or replenishment date, and a failed
lookup becomes a limitation that never carries the failure's own text.
"""

import json
import logging
import re

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import routes_agent
from backend.config import PROJECT_ROOT, settings
from backend.exceptions import (
    InventoryNotFoundError,
    InventoryServiceError,
)
from backend.models.schemas import DisruptionBriefingResponse, RiskLevel
from backend.services import (
    agent_service,
    agent_tools,
    inventory_service,
    shipment_service,
)
from backend.services.agent_service import (
    INVENTORY_SCOPE_LIMITATION,
    INVENTORY_UNAVAILABLE,
    SUPPLIER_SCOPE_LIMITATION,
    UNCOLLECTED_EVIDENCE_LIMITATIONS,
    WEATHER_SCOPE_LIMITATION,
    _format_coverage,
    _summarize_inventory,
    iter_investigation,
    run_investigation,
)
from conftest import INVENTORY_RECORD, SHIPMENT_RECORD, make_prediction


INVESTIGATE_URL = "/api/agent/investigate/SHP-153440"

FAILURE_LIMITATION = f"Inventory evidence was not collected: {INVENTORY_UNAVAILABLE}"

# Details of a record that must never leave the backend, as they appear
# in INVENTORY_RECORD.
UNREPORTED_DETAILS = [
    "warehouse",
    "WH-TEST-07",
    "Rotterdam",
    "Netherlands",
    "SUP-TEST-99",
    "reorder",
    "4321",
    "replenishment_date",
    "2017-06-21",
    "INV-TEST-01",
    "PROD-TEST-01",
    "destination_country_match",
]

INVENTORY_FAILURES = [
    InventoryNotFoundError(
        "No synthetic inventory record was found for product 'Trail Running Shoe'."
    ),
    InventoryServiceError(
        "Inventory data was not found at: C:\\srv\\app\\data\\inventory_tool_data.csv"
    ),
    # Not an inventory error at all: a defect inside the lookup.
    KeyError("_normalized_product_name"),
]

FAILURE_DETAILS = [
    "synthetic inventory record",
    "C:\\srv",
    "inventory_tool_data.csv",
    "_normalized_product_name",
    "KeyError",
]


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes_agent.router)
    return TestClient(app)


def fail_inventory(monkeypatch, error: Exception) -> None:
    def unavailable(shipment):
        raise error

    monkeypatch.setattr(agent_service, "get_inventory_coverage", unavailable)


def use_real_inventory_tool(monkeypatch) -> None:
    """Undo the fixed record so the real tool and service are used."""
    monkeypatch.setattr(
        agent_service,
        "get_inventory_coverage",
        agent_tools.get_inventory_coverage,
    )
    inventory_service.clear_inventory_cache()


@pytest.fixture
def real_inventory(monkeypatch):
    monkeypatch.setattr(
        settings,
        "inventory_data_path",
        PROJECT_ROOT / "data" / "processed" / "inventory_tool_data.csv",
    )
    use_real_inventory_tool(monkeypatch)
    yield
    inventory_service.clear_inventory_cache()


def stream_events(client) -> list[tuple[str, dict]]:
    body = client.get(f"{INVESTIGATE_URL}/stream").text
    events = []
    for block in body.split("\n\n")[:-1]:
        event, data = block.split("\n")
        events.append(
            (
                event.removeprefix("event: "),
                json.loads(data.removeprefix("data: ")),
            )
        )
    return events


# ============================================================
# COLLECTED INVENTORY
# ============================================================


def test_inventory_record_is_summarized_with_fractional_coverage(high_risk):
    briefing = run_investigation("SHP-153440")

    assert briefing.evidence.inventory_summary == (
        "Inventory record for 'Trail Running Shoe': 394 units available "
        "(420 in stock, 26 reserved) against average demand of 23 units "
        "per day, about 17.13 days of coverage. 150 units are recorded as "
        "incoming. Stockout risk on record: LOW. This is a product-level "
        "record; stock availability for this shipment has not been "
        "verified."
    )
    # The whole-day field cannot hold 17.13 and is not rounded into.
    assert briefing.evidence.inventory_coverage_days is None


def test_collected_inventory_adds_the_scope_limitation(high_risk):
    briefing = run_investigation("SHP-153440")

    assert briefing.limitations == [
        INVENTORY_SCOPE_LIMITATION,
        SUPPLIER_SCOPE_LIMITATION,
        WEATHER_SCOPE_LIMITATION,
        *UNCOLLECTED_EVIDENCE_LIMITATIONS,
    ]
    assert not any(
        "Inventory coverage was not collected" in limitation
        for limitation in briefing.limitations
    )


def test_trace_records_only_the_reviewed_inventory_fields(high_risk):
    call = run_investigation("SHP-153440").tool_trace[4]

    assert call.tool == "get_inventory_coverage"
    assert call.input == {"shipment_id": "SHP-153440"}
    assert call.error is None
    assert call.output == {
        "product_name": "Trail Running Shoe",
        "current_stock": 420,
        "reserved_stock": 26,
        "available_stock": 394,
        "daily_demand": 23,
        "safety_stock": 120,
        "incoming_quantity": 150,
        "inventory_coverage_days": 17.13,
        "stockout_risk": "LOW",
        "below_safety_stock": False,
        "matched_on": "product_name (exact, ignoring case and accents)",
        "data_source": "SYNTHETIC_MVP",
        "limitation": INVENTORY_SCOPE_LIMITATION,
    }


def test_response_and_stream_omit_warehouse_supplier_and_reorder_details(
    client,
    high_risk,
):
    response = client.post(INVESTIGATE_URL)
    stream = client.get(f"{INVESTIGATE_URL}/stream")

    assert response.status_code == 200
    assert "get_inventory_coverage" in stream.text
    for detail in UNREPORTED_DETAILS:
        assert detail not in response.text, detail
        assert detail not in stream.text, detail


def test_inventory_wording_makes_no_shipment_specific_or_provenance_claim(
    high_risk,
):
    briefing = run_investigation("SHP-153440")
    user_facing = " ".join(
        [
            briefing.evidence.inventory_summary,
            briefing.summary,
            *briefing.recommended_actions,
            *briefing.limitations,
        ]
    ).lower()

    # Whole words only: "delivery" is not a claim that stock is "live".
    for claim in ["synthetic", "live", "real-time", "confirmed", "fulfil"]:
        assert not re.search(rf"\b{re.escape(claim)}\b", user_facing), claim
    assert "has not been verified" in briefing.evidence.inventory_summary


def test_summary_reports_stock_at_or_below_safety_stock():
    record = INVENTORY_RECORD.model_copy(
        update={
            "current_stock": 453,
            "reserved_stock": 25,
            "available_stock": 428,
            "daily_demand": 109,
            "safety_stock": 572,
            "incoming_quantity": 0,
            "inventory_coverage_days": 3.93,
            "stockout_risk": RiskLevel.HIGH,
            "below_safety_stock": True,
        }
    )

    assert _summarize_inventory(record) == (
        "Inventory record for 'Trail Running Shoe': 428 units available "
        "(453 in stock, 25 reserved) against average demand of 109 units "
        "per day, about 3.93 days of coverage. Available stock is at or "
        "below the safety-stock level of 572 units. No incoming "
        "replenishment is recorded. Stockout risk on record: HIGH. This "
        "is a product-level record; stock availability for this shipment "
        "has not been verified."
    )


def test_whole_word_check_ignores_words_that_only_contain_a_claim():
    assert not re.search(r"\blive\b", "delivery is scheduled for friday")
    assert re.search(r"\blive\b", "live warehouse stock")


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (17.13, "17.13 days"),
        (3.93, "3.93 days"),
        (0.5, "0.5 days"),
        (4.0, "4 days"),
        (1.0, "1 day"),
        (0.0, "0 days"),
        # More significant digits than a general number format keeps.
        (12345.67, "12345.67 days"),
        (1234567.25, "1234567.25 days"),
    ],
)
def test_coverage_is_worded_naturally_and_never_rounded(days, expected):
    assert _format_coverage(days) == expected

    record = INVENTORY_RECORD.model_copy(update={"inventory_coverage_days": days})

    assert f"about {expected} of coverage." in _summarize_inventory(record)


def test_inventory_is_collected_from_the_dataset_by_product_name(
    high_risk,
    real_inventory,
    monkeypatch,
):
    record = {**SHIPMENT_RECORD, "product_name": "Perfect Fitness Perfect Rip Deck"}
    monkeypatch.setattr(
        shipment_service,
        "load_shipment_data",
        lambda: pd.DataFrame([record]),
    )

    briefing = run_investigation("SHP-153440")

    assert briefing.tool_trace[4].status == "success"
    assert briefing.tool_trace[4].output["inventory_coverage_days"] == 3.93
    assert "about 3.93 days of coverage" in briefing.evidence.inventory_summary
    assert INVENTORY_SCOPE_LIMITATION in briefing.limitations


# ============================================================
# INVENTORY THAT COULD NOT BE COLLECTED
# ============================================================


@pytest.mark.parametrize("error", INVENTORY_FAILURES, ids=lambda e: type(e).__name__)
def test_inventory_failure_becomes_a_safe_limitation(
    high_risk,
    monkeypatch,
    error,
):
    fail_inventory(monkeypatch, error)

    briefing = run_investigation("SHP-153440")

    # The briefing is still produced from the other evidence.
    assert isinstance(briefing, DisruptionBriefingResponse)
    assert briefing.evidence.weather_summary is not None
    assert briefing.evidence.historical_delay_summary is not None
    assert briefing.evidence.inventory_summary is None
    assert briefing.evidence.inventory_coverage_days is None

    failed_call = briefing.tool_trace[4]
    assert failed_call.tool == "get_inventory_coverage"
    assert failed_call.status == "error"
    assert failed_call.output is None
    assert failed_call.error == INVENTORY_UNAVAILABLE

    assert briefing.limitations == [
        FAILURE_LIMITATION,
        SUPPLIER_SCOPE_LIMITATION,
        WEATHER_SCOPE_LIMITATION,
        *UNCOLLECTED_EVIDENCE_LIMITATIONS,
    ]


@pytest.mark.parametrize("error", INVENTORY_FAILURES, ids=lambda e: type(e).__name__)
def test_inventory_failure_details_never_reach_the_client(
    client,
    high_risk,
    monkeypatch,
    error,
):
    fail_inventory(monkeypatch, error)

    response = client.post(INVESTIGATE_URL)
    stream = client.get(f"{INVESTIGATE_URL}/stream")

    assert response.status_code == 200
    for detail in FAILURE_DETAILS:
        # JSON escapes backslashes, so both spellings are checked.
        for spelling in (detail, json.dumps(detail)[1:-1]):
            assert spelling not in response.text, detail
            assert spelling not in stream.text, detail


def test_inventory_failure_is_logged_for_operators(
    high_risk,
    monkeypatch,
    caplog,
):
    fail_inventory(
        monkeypatch,
        InventoryServiceError("Inventory data was not found at: /srv/data.csv"),
    )

    with caplog.at_level(logging.WARNING, logger=agent_service.logger.name):
        run_investigation("SHP-153440")

    assert "get_inventory_coverage failed" in caplog.text
    assert "/srv/data.csv" in caplog.text


def test_inventory_failure_emits_tool_error_and_the_stream_completes(
    client,
    high_risk,
    monkeypatch,
):
    fail_inventory(monkeypatch, InventoryNotFoundError("no record"))

    events = stream_events(client)

    # The failure is reported, then the supplier step still runs.
    assert [
        (name, data["name"]) for name, data in events if name.startswith("tool_")
    ][-4:] == [
        ("tool_start", "get_inventory_coverage"),
        ("tool_error", "get_inventory_coverage"),
        ("tool_start", "find_alternative_supplier"),
        ("tool_complete", "find_alternative_supplier"),
    ]
    assert events[-5] == (
        "tool_error",
        {
            "name": "get_inventory_coverage",
            "input": {"shipment_id": "SHP-153440"},
            "output": None,
            "status": "error",
            "error": INVENTORY_UNAVAILABLE,
        },
    )
    assert [name for name, _ in events[-2:]] == ["message", "done"]

    done = events[-1][1]
    assert done["limitations"][0] == FAILURE_LIMITATION
    assert done == client.post(INVESTIGATE_URL).json()


def test_product_without_an_inventory_record_still_gets_a_briefing(
    high_risk,
    real_inventory,
):
    # "Trail Running Shoe" is not in the inventory dataset.
    briefing = run_investigation("SHP-153440")

    assert briefing.tool_trace[4].error == INVENTORY_UNAVAILABLE
    assert briefing.evidence.inventory_summary is None
    assert briefing.limitations[0] == FAILURE_LIMITATION


def test_missing_inventory_dataset_does_not_expose_its_path(
    client,
    high_risk,
    monkeypatch,
    tmp_path,
):
    missing = tmp_path / "private" / "inventory_tool_data.csv"
    monkeypatch.setattr(settings, "inventory_data_path", missing)
    use_real_inventory_tool(monkeypatch)

    try:
        response = client.post(INVESTIGATE_URL)
    finally:
        inventory_service.clear_inventory_cache()

    assert response.status_code == 200
    assert response.json()["tool_trace"][4]["error"] == INVENTORY_UNAVAILABLE
    assert response.json()["limitations"][0] == FAILURE_LIMITATION
    assert "private" not in response.text
    assert tmp_path.name not in response.text


def test_inventory_that_cannot_be_summarized_becomes_a_limitation(
    high_risk,
    monkeypatch,
):
    def defective_summary(record):
        raise TypeError("summary defect in warehouse WH-TEST-07")

    monkeypatch.setattr(agent_service, "_summarize_inventory", defective_summary)

    briefing = run_investigation("SHP-153440")

    # The lookup answered, so the trace keeps its reviewed record.
    call = briefing.tool_trace[4]
    assert call.status == "success"
    assert "warehouse_id" not in call.output
    assert briefing.evidence.inventory_summary is None
    assert briefing.limitations[0] == FAILURE_LIMITATION
    assert "WH-TEST-07" not in briefing.model_dump_json()


def test_trace_record_that_cannot_be_built_becomes_a_safe_limitation(
    client,
    high_risk,
    monkeypatch,
):
    def defective_trace_output(record):
        raise RuntimeError(
            f"trace defect for {record.warehouse_id} at C:\\srv\\inventory.csv"
        )

    monkeypatch.setattr(
        agent_service,
        "_inventory_trace_output",
        defective_trace_output,
    )

    response = client.post(INVESTIGATE_URL)
    events = stream_events(client)
    stream_text = client.get(f"{INVESTIGATE_URL}/stream").text

    # The investigation continues and the briefing is returned.
    assert response.status_code == 200
    body = response.json()
    assert body["evidence"]["weather_summary"] is not None
    assert body["evidence"]["inventory_summary"] is None

    # No record could be reported, so the call is a failure with the
    # fixed message and nothing of the lookup's result.
    assert body["tool_trace"][4] == {
        "tool": "get_inventory_coverage",
        "input": {"shipment_id": "SHP-153440"},
        "output": None,
        "status": "error",
        "error": INVENTORY_UNAVAILABLE,
    }
    assert body["limitations"][0] == FAILURE_LIMITATION
    assert INVENTORY_SCOPE_LIMITATION not in body["limitations"]

    assert events[-5][0] == "tool_error"
    assert events[-5][1]["error"] == INVENTORY_UNAVAILABLE
    assert events[-1] == ("done", body)

    for detail in ["trace defect", "RuntimeError", "srv", "inventory.csv"]:
        assert detail not in response.text, detail
        assert detail not in stream_text, detail
    for detail in UNREPORTED_DETAILS:
        assert detail not in response.text, detail
        assert detail not in stream_text, detail


def test_inventory_failure_alongside_other_failures_keeps_their_order(
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
    fail_inventory(monkeypatch, InventoryNotFoundError("no record"))

    briefing = run_investigation("SHP-153440")

    assert [(call.tool, call.status.value) for call in briefing.tool_trace] == [
        ("get_delay_risk", "success"),
        ("get_shipment", "success"),
        ("get_historical_delay_context", "error"),
        ("get_destination_weather", "success"),
        ("get_inventory_coverage", "error"),
        ("find_alternative_supplier", "success"),
    ]
    # Other sources keep reporting their own failure text.
    assert briefing.limitations[:2] == [
        "Historical delay context was not collected: context source unavailable",
        FAILURE_LIMITATION,
    ]


# ============================================================
# RISK GATE
# ============================================================


def test_low_risk_shipment_never_reaches_the_inventory_tool(
    client,
    low_risk,
    monkeypatch,
):
    def fail_if_called(shipment):
        raise AssertionError("inventory must not run for a LOW risk shipment")

    monkeypatch.setattr(agent_service, "get_inventory_coverage", fail_if_called)

    response = client.post(INVESTIGATE_URL)
    events = stream_events(client)

    assert response.status_code == 400
    assert "LOW risk" in response.json()["detail"]
    assert [name for name, _ in events] == ["tool_start", "tool_complete", "error"]
    assert events[-1][1]["code"] == "investigation_not_required"


@pytest.mark.parametrize("risk_level", [RiskLevel.MEDIUM, RiskLevel.HIGH])
def test_medium_and_high_risk_shipments_collect_inventory_after_weather(
    shipment_data,
    monkeypatch,
    risk_level,
):
    monkeypatch.setattr(
        agent_tools,
        "predict_delay_risk",
        lambda shipment_id: make_prediction(risk_level, 0.6, True),
    )

    tools = [
        event.data["name"]
        for event in iter_investigation("SHP-153440")
        if event.event == "tool_complete"
    ]

    assert tools == [
        "get_delay_risk",
        "get_shipment",
        "get_historical_delay_context",
        "get_destination_weather",
        "get_inventory_coverage",
        "find_alternative_supplier",
    ]
