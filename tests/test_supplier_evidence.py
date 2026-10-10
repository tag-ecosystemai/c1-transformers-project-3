"""
Alternative supplier candidates as an optional evidence source.

Supplier candidates are matched on product category only. They are
suggestions for human review: the supplier records hold no available
capacity, commercial terms, live status or delivery dates, so nothing
reported here says a supplier is available or committed. A lookup that
fails or returns nothing usable becomes a limitation and never ends
the investigation.
"""

import json
import logging
import re

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import routes_agent
from backend.models.schemas import DisruptionBriefingResponse, RiskLevel
from backend.services import (
    agent_service,
    agent_tools,
    briefing_service,
    shipment_service,
)
from backend.services.agent_service import (
    INVENTORY_SCOPE_LIMITATION,
    SUPPLIER_CANDIDATE_TRACE_FIELDS,
    SUPPLIER_MATCHED_ON,
    SUPPLIER_SCOPE_LIMITATION,
    SUPPLIER_SELECTION_BASIS,
    SUPPLIER_UNAVAILABLE,
    UNCOLLECTED_EVIDENCE_LIMITATIONS,
    WEATHER_SCOPE_LIMITATION,
    _summarize_supplier,
    run_investigation,
)
from backend.services.briefing_service import RETRIEVAL_UNAVAILABLE_LIMITATION
from backend.services.supplier_service import (
    SupplierNotFoundError,
    SupplierServiceError,
)
from conftest import (
    HIGH_RISK_SUPPLIER_CANDIDATE,
    SHIPMENT_RECORD,
    SUPPLIER_RECOMMENDATION,
    SUPPLIER_SERVICE_NOTE,
)
from rag.retrieval import RAGRetrievalError


INVESTIGATE_URL = "/api/agent/investigate/SHP-153440"

SUPPLIER_SUMMARY = (
    "Alternative supplier candidate for product category 'Cleats': "
    "NorthStar Logistics (SUP-TEST-03), based in Bután, supplying "
    "Sporting Goods. On record: average lead time 8.5 days, on-time "
    "delivery rate 87.7%, supplier risk MEDIUM (19.68/100). It was "
    "selected from 2 candidates on record for the category. This is a "
    "category-level suggestion; supplier availability, capacity for the "
    "required quantity and commercial terms have not been verified."
)

FAILURE_LIMITATION = f"Supplier evidence was not collected: {SUPPLIER_UNAVAILABLE}"

SUPPLIER_FAILURES = [
    SupplierNotFoundError(
        "No synthetic supplier candidate was found for shipment category "
        "'Cleats'. Compatible supplier categories checked: cleats."
    ),
    SupplierServiceError(
        "Supplier data was not found at: "
        "C:\\srv\\app\\data\\processed\\supplier_tool_data.csv"
    ),
    ValueError("The destination country cannot be empty."),
    # Not a supplier error at all: a defect inside the lookup.
    KeyError("_normalized_category"),
]

FAILURE_DETAILS = [
    "synthetic supplier candidate",
    "Compatible supplier categories",
    "C:\\srv",
    "supplier_tool_data.csv",
    "destination country cannot be empty",
    "_normalized_category",
    "KeyError",
    "SupplierServiceError",
]

# Operational figures of a supplier record that nothing shown to a
# reader depends on, with the values they have in the fixed
# recommendation. None of them may appear in a response or a stream.
EXCLUDED_SUPPLIER_FIELDS = [
    "cancellation_rate",
    "quality_issue_rate",
    "capacity_utilization",
]

EXCLUDED_SUPPLIER_VALUES = ["0.088", "0.066", "0.584"]

# The shipment's own details, already recorded by the shipment step.
REDUNDANT_SUPPLIER_KEYS = ["destination_country", "required_quantity"]

REDUCED_CANDIDATE = {
    "supplier_id": "SUP-TEST-03",
    "supplier_name": "NorthStar Logistics",
    "supplier_country": "Bután",
    "product_category": "Sporting Goods",
    "average_lead_time_days": 8.5,
    "on_time_delivery_rate": 0.877,
    "supplier_risk_score": 19.68,
    "supplier_risk_level": "MEDIUM",
    "data_source": "SYNTHETIC_MVP",
}

REDUCED_HIGH_RISK_CANDIDATE = {
    "supplier_id": "SUP-TEST-16",
    "supplier_name": "DirectSource Global",
    "supplier_country": "Noruega",
    "product_category": "Men's Footwear",
    "average_lead_time_days": 2.3,
    "on_time_delivery_rate": 0.877,
    "supplier_risk_score": 25.7,
    "supplier_risk_level": "HIGH",
    "data_source": "SYNTHETIC_MVP",
}

# Statements the supplier records cannot support. Whole words only:
# "availability ... not been verified" is not a claim of "available".
UNSUPPORTED_SUPPLIER_CLAIMS = [
    "synthetic",
    "available",
    "confirmed",
    "guaranteed",
    "contracted",
    "approved",
    "committed",
    "commitment",
    "secured",
    "will deliver",
    "can supply",
    "can fulfil",
    "in time",
]


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes_agent.router)
    return TestClient(app)


def use_suppliers(monkeypatch, lookup) -> None:
    monkeypatch.setattr(agent_service, "get_alternative_suppliers", lookup)


def fail_suppliers(monkeypatch, error: Exception) -> None:
    def unavailable(shipment):
        raise error

    use_suppliers(monkeypatch, unavailable)


def use_real_supplier_tool(monkeypatch) -> None:
    """Undo the fixed recommendation so the real tool and dataset run."""
    use_suppliers(monkeypatch, agent_tools.get_alternative_suppliers)


def fail_retrieval(monkeypatch) -> None:
    def unavailable(query, k=5):
        raise RAGRetrievalError("The RAG vector store does not exist.")

    def azure_must_not_run(**kwargs):
        raise AssertionError("Azure OpenAI must not be called")

    monkeypatch.setattr(
        briefing_service,
        "retrieve_operational_knowledge",
        unavailable,
    )
    monkeypatch.setattr(
        briefing_service,
        "generate_azure_briefing",
        azure_must_not_run,
    )


def supplier_call(briefing: DisruptionBriefingResponse):
    return next(
        call
        for call in briefing.tool_trace
        if call.tool == "find_alternative_supplier"
    )


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


def supplier_statements(briefing: DisruptionBriefingResponse) -> str:
    """Every sentence the briefing gives a reader about suppliers."""
    texts = [
        briefing.evidence.supplier_status or "",
        briefing.summary,
        *briefing.recommended_actions,
        *briefing.limitations,
    ]
    sentences = [
        sentence
        for text in texts
        for sentence in re.split(r"(?<=[.!?])\s+", text)
    ]
    return " ".join(
        sentence for sentence in sentences if "supplier" in sentence.lower()
    )


def assert_no_unsupported_supplier_claims(briefing) -> None:
    statements = supplier_statements(briefing).lower()

    for claim in UNSUPPORTED_SUPPLIER_CLAIMS:
        assert not re.search(rf"\b{re.escape(claim)}\b", statements), claim


# ============================================================
# COLLECTED SUPPLIER EVIDENCE
# ============================================================


def test_supplier_candidate_is_collected_as_evidence(high_risk):
    briefing = run_investigation("SHP-153440")

    assert briefing.evidence.supplier_status == SUPPLIER_SUMMARY
    assert [call.tool for call in briefing.tool_trace] == [
        "get_delay_risk",
        "get_shipment",
        "get_historical_delay_context",
        "get_destination_weather",
        "get_inventory_coverage",
        "find_alternative_supplier",
    ]
    assert all(call.status == "success" for call in briefing.tool_trace)


def test_collected_supplier_evidence_adds_the_scope_limitation(high_risk):
    briefing = run_investigation("SHP-153440")

    assert briefing.limitations == [
        INVENTORY_SCOPE_LIMITATION,
        SUPPLIER_SCOPE_LIMITATION,
        WEATHER_SCOPE_LIMITATION,
        *UNCOLLECTED_EVIDENCE_LIMITATIONS,
    ]
    assert not any(
        "Supplier status was not collected" in limitation
        for limitation in briefing.limitations
    )


def test_trace_records_only_the_reviewed_supplier_fields(high_risk):
    call = supplier_call(run_investigation("SHP-153440"))

    assert call.input == {"shipment_id": "SHP-153440"}
    assert call.error is None
    assert call.output == {
        "category": "Cleats",
        "matched_on": (
            "product category (the shipment's category or a listed "
            "compatible supplier category)"
        ),
        "selection_basis": (
            "Candidates are ranked by the supplier service: a supplier "
            "country matching the shipment destination first, then lower "
            "supplier risk and recorded performance. The suggested "
            "candidate is the highest-ranked one with LOW or MEDIUM "
            "supplier risk."
        ),
        "candidate_count": 2,
        "recommended_supplier": REDUCED_CANDIDATE,
        "alternatives": [REDUCED_CANDIDATE, REDUCED_HIGH_RISK_CANDIDATE],
        # What the records do not establish stays explicit.
        "quantity_capacity_verified": False,
        "data_source": "SYNTHETIC_MVP",
        "limitation": SUPPLIER_SCOPE_LIMITATION,
    }
    assert call.output["matched_on"] == SUPPLIER_MATCHED_ON
    assert call.output["selection_basis"] == SUPPLIER_SELECTION_BASIS
    # The service's own note is not passed on.
    assert SUPPLIER_SERVICE_NOTE not in json.dumps(call.output)


def test_trace_keeps_what_identifies_and_explains_each_candidate(high_risk):
    output = supplier_call(run_investigation("SHP-153440")).output

    for candidate in [output["recommended_supplier"], *output["alternatives"]]:
        assert set(candidate) == SUPPLIER_CANDIDATE_TRACE_FIELDS
        for excluded in EXCLUDED_SUPPLIER_FIELDS:
            assert excluded not in candidate, excluded

    # Candidates can still be told apart.
    assert [c["supplier_id"] for c in output["alternatives"]] == [
        "SUP-TEST-03",
        "SUP-TEST-16",
    ]
    for redundant in REDUNDANT_SUPPLIER_KEYS:
        assert redundant not in output, redundant


def test_excluded_supplier_fields_never_reach_the_client(client, high_risk):
    response = client.post(INVESTIGATE_URL)
    stream = client.get(f"{INVESTIGATE_URL}/stream")

    assert response.status_code == 200
    # The step and its candidates are reported...
    assert "find_alternative_supplier" in stream.text
    assert "NorthStar Logistics" in response.text
    # ...without the figures nothing shown depends on.
    for excluded in [*EXCLUDED_SUPPLIER_FIELDS, *EXCLUDED_SUPPLIER_VALUES]:
        assert excluded not in response.text, excluded
        assert excluded not in stream.text, excluded

    done = stream_events(client)[-1][1]
    assert done == response.json()


def test_excluded_supplier_fields_stay_out_when_no_supplier_is_suggested(
    client,
    high_risk,
    monkeypatch,
):
    no_suggestion = SUPPLIER_RECOMMENDATION.model_copy(
        update={
            "recommended_supplier": None,
            "alternatives": [HIGH_RISK_SUPPLIER_CANDIDATE],
            "candidate_count": 1,
        }
    )
    use_suppliers(monkeypatch, lambda shipment: no_suggestion)

    response = client.post(INVESTIGATE_URL)
    output = next(
        call["output"]
        for call in response.json()["tool_trace"]
        if call["tool"] == "find_alternative_supplier"
    )

    assert output["recommended_supplier"] is None
    assert output["alternatives"] == [REDUCED_HIGH_RISK_CANDIDATE]
    assert output["candidate_count"] == 1
    for excluded in [*EXCLUDED_SUPPLIER_FIELDS, *EXCLUDED_SUPPLIER_VALUES]:
        assert excluded not in response.text, excluded


def test_reduced_trace_still_supports_the_briefing(client, high_risk, monkeypatch):
    generated = client.post(INVESTIGATE_URL).json()
    fail_retrieval(monkeypatch)
    evidence_only = client.post(INVESTIGATE_URL).json()

    for body in (generated, evidence_only):
        # The briefing is written from the supplier summary, which the
        # reduced trace does not change.
        assert body["evidence"]["supplier_status"] == SUPPLIER_SUMMARY
        assert SUPPLIER_SUMMARY in body["summary"]
        assert SUPPLIER_SCOPE_LIMITATION in body["limitations"]
        assert body["recommended_actions"]

    assert generated["rag_policy_citations"]
    assert evidence_only["rag_policy_citations"] == []


def test_supplier_candidate_is_found_in_the_dataset_by_category(
    high_risk,
    monkeypatch,
):
    use_real_supplier_tool(monkeypatch)

    briefing = run_investigation("SHP-153440")

    call = supplier_call(briefing)
    assert call.status == "success"
    assert call.output["category"] == "Cleats"
    assert call.output["quantity_capacity_verified"] is False
    assert call.output["candidate_count"] >= 1
    assert call.output["alternatives"]
    # The real records are reduced in the same way.
    for candidate in call.output["alternatives"]:
        assert set(candidate) == SUPPLIER_CANDIDATE_TRACE_FIELDS
    for excluded in [*EXCLUDED_SUPPLIER_FIELDS, *REDUNDANT_SUPPLIER_KEYS]:
        assert excluded not in json.dumps(call.output), excluded
    assert briefing.evidence.supplier_status.startswith(
        "Alternative supplier candidate for product category 'Cleats': "
    ) or briefing.evidence.supplier_status.startswith(
        "No alternative supplier is suggested for product category 'Cleats'"
    )
    assert SUPPLIER_SCOPE_LIMITATION in briefing.limitations
    assert_no_unsupported_supplier_claims(briefing)


# ============================================================
# NO RECOMMENDATION
# ============================================================


def test_only_high_risk_candidates_are_reported_without_a_suggestion(
    high_risk,
    monkeypatch,
):
    no_suggestion = SUPPLIER_RECOMMENDATION.model_copy(
        update={
            "recommended_supplier": None,
            "alternatives": [HIGH_RISK_SUPPLIER_CANDIDATE],
            "candidate_count": 1,
        }
    )
    use_suppliers(monkeypatch, lambda shipment: no_suggestion)

    briefing = run_investigation("SHP-153440")

    assert briefing.evidence.supplier_status == (
        "No alternative supplier is suggested for product category "
        "'Cleats': the 1 candidate on record for the category is "
        "classified as high risk and needs human review."
    )
    # The high-risk candidate is not named as an alternative.
    assert "DirectSource Global" not in briefing.evidence.supplier_status
    assert supplier_call(briefing).status == "success"
    assert SUPPLIER_SCOPE_LIMITATION in briefing.limitations
    assert_no_unsupported_supplier_claims(briefing)


def test_category_without_candidates_becomes_a_limitation(
    high_risk,
    monkeypatch,
):
    # The real service, for a category no supplier record covers.
    record = {**SHIPMENT_RECORD, "category": "Category Without Suppliers"}
    monkeypatch.setattr(
        shipment_service,
        "load_shipment_data",
        lambda: pd.DataFrame([record]),
    )
    use_real_supplier_tool(monkeypatch)

    briefing = run_investigation("SHP-153440")

    assert isinstance(briefing, DisruptionBriefingResponse)
    assert briefing.evidence.supplier_status is None
    call = supplier_call(briefing)
    assert call.status == "error"
    assert call.error == SUPPLIER_UNAVAILABLE
    assert FAILURE_LIMITATION in briefing.limitations
    assert SUPPLIER_SCOPE_LIMITATION not in briefing.limitations


def test_result_without_candidates_is_not_reported_as_evidence(
    high_risk,
    monkeypatch,
):
    empty = SUPPLIER_RECOMMENDATION.model_copy(
        update={
            "recommended_supplier": None,
            "alternatives": [],
            "candidate_count": 0,
        }
    )
    use_suppliers(monkeypatch, lambda shipment: empty)

    briefing = run_investigation("SHP-153440")

    assert briefing.evidence.supplier_status is None
    assert FAILURE_LIMITATION in briefing.limitations
    assert SUPPLIER_SCOPE_LIMITATION not in briefing.limitations
    # The lookup answered, so the trace records what it returned.
    call = supplier_call(briefing)
    assert call.status == "success"
    assert call.output["alternatives"] == []
    assert "Supplier availability has not yet been assessed." in briefing.summary


# ============================================================
# SUPPLIER TOOL EXCEPTIONS
# ============================================================


@pytest.mark.parametrize("error", SUPPLIER_FAILURES, ids=lambda e: type(e).__name__)
def test_supplier_failure_becomes_a_safe_limitation(
    high_risk,
    monkeypatch,
    error,
):
    fail_suppliers(monkeypatch, error)

    briefing = run_investigation("SHP-153440")

    # The briefing is still produced from the other evidence.
    assert isinstance(briefing, DisruptionBriefingResponse)
    assert briefing.evidence.supplier_status is None
    assert briefing.evidence.weather_summary is not None
    assert briefing.evidence.historical_delay_summary is not None
    assert briefing.evidence.inventory_summary is not None

    call = supplier_call(briefing)
    assert call.status == "error"
    assert call.output is None
    assert call.error == SUPPLIER_UNAVAILABLE

    assert briefing.limitations == [
        INVENTORY_SCOPE_LIMITATION,
        FAILURE_LIMITATION,
        WEATHER_SCOPE_LIMITATION,
        *UNCOLLECTED_EVIDENCE_LIMITATIONS,
    ]
    assert "Supplier availability has not yet been assessed." in briefing.summary


@pytest.mark.parametrize("error", SUPPLIER_FAILURES, ids=lambda e: type(e).__name__)
def test_supplier_failure_details_never_reach_the_client(
    client,
    high_risk,
    monkeypatch,
    error,
):
    fail_suppliers(monkeypatch, error)

    response = client.post(INVESTIGATE_URL)
    stream = client.get(f"{INVESTIGATE_URL}/stream")

    assert response.status_code == 200
    for detail in FAILURE_DETAILS:
        # JSON escapes backslashes, so both spellings are checked.
        for spelling in (detail, json.dumps(detail)[1:-1]):
            assert spelling not in response.text, detail
            assert spelling not in stream.text, detail


def test_supplier_failure_emits_tool_error_and_the_stream_completes(
    client,
    high_risk,
    monkeypatch,
):
    fail_suppliers(monkeypatch, SupplierServiceError("dataset unreadable"))

    events = stream_events(client)

    assert events[-3] == (
        "tool_error",
        {
            "name": "find_alternative_supplier",
            "input": {"shipment_id": "SHP-153440"},
            "output": None,
            "status": "error",
            "error": SUPPLIER_UNAVAILABLE,
        },
    )
    assert [name for name, _ in events[-2:]] == ["message", "done"]

    done = events[-1][1]
    assert FAILURE_LIMITATION in done["limitations"]
    assert done == client.post(INVESTIGATE_URL).json()


def test_supplier_failure_is_logged_for_operators(
    high_risk,
    monkeypatch,
    caplog,
):
    fail_suppliers(
        monkeypatch,
        SupplierServiceError("Supplier data was not found at: /srv/suppliers.csv"),
    )

    with caplog.at_level(logging.WARNING, logger=agent_service.logger.name):
        run_investigation("SHP-153440")

    assert "find_alternative_supplier failed" in caplog.text
    assert "/srv/suppliers.csv" in caplog.text


# ============================================================
# SUPPLIER EVIDENCE IN THE BRIEFING
# ============================================================


def test_generated_briefing_is_given_the_supplier_evidence(
    high_risk,
    monkeypatch,
):
    received = []
    real_briefing = agent_service.generate_rag_briefing

    def recording_briefing(**kwargs):
        received.append(kwargs["evidence"])
        return real_briefing(**kwargs)

    monkeypatch.setattr(agent_service, "generate_rag_briefing", recording_briefing)

    briefing = run_investigation("SHP-153440")

    assert received[0].supplier_status == SUPPLIER_SUMMARY
    assert SUPPLIER_SUMMARY in briefing.summary
    assert "Supplier availability has not yet been assessed." not in briefing.summary


def test_retrieval_query_includes_the_supplier_evidence(high_risk, monkeypatch):
    queries = []
    real_retrieve = briefing_service.retrieve_operational_knowledge

    def recording_retrieve(query, k=5):
        queries.append(query)
        return real_retrieve(query, k)

    monkeypatch.setattr(
        briefing_service,
        "retrieve_operational_knowledge",
        recording_retrieve,
    )

    run_investigation("SHP-153440")

    assert f"Supplier evidence: {SUPPLIER_SUMMARY}" in queries[0]
    assert "Supplier evidence is not currently available." not in queries[0]


def test_briefing_states_when_supplier_evidence_is_unavailable(
    high_risk,
    monkeypatch,
):
    fail_suppliers(monkeypatch, SupplierNotFoundError("no candidates"))
    fail_retrieval(monkeypatch)

    briefing = run_investigation("SHP-153440")

    assert "Supplier availability has not yet been assessed." in briefing.summary
    assert (
        "Obtain supplier availability and performance evidence before "
        "recommending an alternative supplier."
        in briefing.recommended_actions
    )
    assert "NorthStar Logistics" not in briefing.model_dump_json()


# ============================================================
# WITHOUT RETRIEVED DOCUMENTS
# ============================================================


def test_supplier_evidence_is_used_when_retrieval_is_unavailable(
    client,
    high_risk,
    monkeypatch,
):
    fail_retrieval(monkeypatch)

    response = client.post(INVESTIGATE_URL)

    assert response.status_code == 200
    body = response.json()
    # No documents were retrieved, so none is cited.
    assert body["rag_policy_citations"] == []
    assert f"Supplier evidence: {SUPPLIER_SUMMARY}" in body["summary"]
    assert (
        "Review the alternative supplier candidate when evaluating "
        "sourcing options. Supplier availability, capacity and "
        "commercial terms are not verified and require human validation "
        "before any supplier change."
        in body["recommended_actions"]
    )
    assert body["limitations"] == [
        INVENTORY_SCOPE_LIMITATION,
        SUPPLIER_SCOPE_LIMITATION,
        RETRIEVAL_UNAVAILABLE_LIMITATION,
        WEATHER_SCOPE_LIMITATION,
        *UNCOLLECTED_EVIDENCE_LIMITATIONS,
    ]
    assert ".pdf" not in response.text
    assert_no_unsupported_supplier_claims(
        DisruptionBriefingResponse.model_validate(body)
    )


def test_investigation_completes_when_suppliers_and_retrieval_are_unavailable(
    client,
    high_risk,
    monkeypatch,
):
    fail_suppliers(
        monkeypatch,
        SupplierServiceError("Supplier data was not found at: C:\\srv\\s.csv"),
    )
    fail_retrieval(monkeypatch)

    response = client.post(INVESTIGATE_URL)
    events = stream_events(client)

    assert response.status_code == 200
    body = response.json()
    DisruptionBriefingResponse.model_validate(body)
    assert body["rag_policy_citations"] == []
    assert body["evidence"]["supplier_status"] is None
    # The rest of the evidence still reaches the briefing.
    assert body["evidence"]["inventory_summary"] in body["summary"]
    assert body["evidence"]["weather_summary"] in body["summary"]
    assert body["recommended_actions"]
    assert body["limitations"] == [
        INVENTORY_SCOPE_LIMITATION,
        FAILURE_LIMITATION,
        RETRIEVAL_UNAVAILABLE_LIMITATION,
        WEATHER_SCOPE_LIMITATION,
        *UNCOLLECTED_EVIDENCE_LIMITATIONS,
    ]
    assert "C:" not in response.text.replace("SHP-153440:", "")
    assert events[-1] == ("done", body)


# ============================================================
# NO UNSUPPORTED CLAIMS
# ============================================================


def test_supplier_wording_claims_no_availability_or_commitment(
    high_risk,
    monkeypatch,
):
    generated = run_investigation("SHP-153440")
    fail_retrieval(monkeypatch)
    evidence_only = run_investigation("SHP-153440")

    for briefing in (generated, evidence_only):
        assert_no_unsupported_supplier_claims(briefing)
        assert "have not been verified" in briefing.evidence.supplier_status
        assert SUPPLIER_SCOPE_LIMITATION in briefing.limitations


def test_summary_reports_only_what_the_supplier_record_holds():
    summary = _summarize_supplier(SUPPLIER_RECOMMENDATION)

    assert summary == SUPPLIER_SUMMARY
    # The required quantity is not presented as capacity the supplier
    # has, and no delivery date is derived from the average lead time.
    assert "2 units" not in summary
    assert not re.search(r"\b\d{4}-\d{2}-\d{2}\b", summary)
    assert "on record" in summary.lower()
    # Figures the summary does not need are not reported.
    for unused in ("0.584", "58.4%", "8.8%", "6.6%"):
        assert unused not in summary


def test_inventory_evidence_is_unchanged_by_the_supplier_step(high_risk):
    briefing = run_investigation("SHP-153440")

    inventory_call = briefing.tool_trace[4]
    assert inventory_call.tool == "get_inventory_coverage"
    assert "warehouse_id" not in inventory_call.output
    assert "supplier_id" not in inventory_call.output
    assert briefing.evidence.inventory_coverage_days is None
    assert briefing.evidence.inventory_summary.endswith(
        "stock availability for this shipment has not been verified."
    )
    assert "destination_country_match" not in briefing.model_dump_json()


# ============================================================
# RISK GATE
# ============================================================


def test_low_risk_shipment_never_reaches_the_supplier_tool(
    client,
    low_risk,
    monkeypatch,
):
    def fail_if_called(shipment):
        raise AssertionError("suppliers must not be looked up for LOW risk")

    use_suppliers(monkeypatch, fail_if_called)

    response = client.post(INVESTIGATE_URL)

    assert response.status_code == 400
    assert "LOW risk" in response.json()["detail"]


@pytest.mark.parametrize("risk_level", [RiskLevel.MEDIUM, RiskLevel.HIGH])
def test_medium_and_high_risk_shipments_collect_supplier_evidence(
    shipment_data,
    monkeypatch,
    risk_level,
):
    from conftest import make_prediction

    monkeypatch.setattr(
        agent_tools,
        "predict_delay_risk",
        lambda shipment_id: make_prediction(risk_level, 0.6, True),
    )

    briefing = run_investigation("SHP-153440")

    assert briefing.risk_level == risk_level
    assert briefing.evidence.supplier_status == SUPPLIER_SUMMARY
