"""
The briefing when supporting documents or Azure OpenAI are unavailable.

Retrieval and the language model are optional. Without retrieved
documents the briefing is built from the collected evidence alone,
cites nothing and says so; citations are only ever the sources of
documents that were actually retrieved.
"""

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import rag.retrieval
from backend.api import routes_agent
from backend.exceptions import AzureOpenAIServiceError
from backend.models.schemas import (
    DisruptionBriefingResponse,
    LLMBriefingContent,
    RiskLevel,
    ToolEvidence,
)
from backend.services import agent_service, briefing_service
from backend.services.agent_service import (
    INVENTORY_SCOPE_LIMITATION,
    SUPPLIER_SCOPE_LIMITATION,
    UNCOLLECTED_EVIDENCE_LIMITATIONS,
    WEATHER_SCOPE_LIMITATION,
    run_investigation,
)
from backend.services.briefing_service import (
    DETERMINISTIC_BRIEFING_LIMITATION,
    NO_DOCUMENTS_RETRIEVED_LIMITATION,
    RETRIEVAL_UNAVAILABLE_LIMITATION,
    generate_rag_briefing,
)
from rag.retrieval import RAGRetrievalError


INVESTIGATE_URL = "/api/agent/investigate/SHP-153440"

EVIDENCE = ToolEvidence(
    shipment_summary="SHP-153440: 2 x Trail Running Shoe to Vassouras.",
    historical_delay_summary="Historical delay rates: product 57.0%.",
    weather_summary="Observed weather: slight rain (low severity).",
    inventory_summary=(
        "Inventory record for 'Trail Running Shoe': 394 units available, "
        "about 17.13 days of coverage. This is a product-level record; "
        "stock availability for this shipment has not been verified."
    ),
)

RETRIEVED = [
    {
        "rank": 1,
        "source": "01_shipment_delay_escalation.pdf",
        "source_path": "01_shipment_delay_escalation.pdf",
        "relevance_score": 0.91,
        "content": "Elevated-risk shipments require human review.",
        "metadata": {"data_source": "SYNTHETIC_MVP"},
    },
    {
        "rank": 2,
        "source": "04_inventory_stockout_response.pdf",
        "source_path": "04_inventory_stockout_response.pdf",
        "relevance_score": 0.83,
        "content": "Confirm stock before relying on inventory.",
        "metadata": {"data_source": "SYNTHETIC_MVP"},
    },
    # A second chunk of a document already cited.
    {
        "rank": 3,
        "source": "01_shipment_delay_escalation.pdf",
        "source_path": "01_shipment_delay_escalation.pdf",
        "relevance_score": 0.80,
        "content": "Escalate when several risk factors coincide.",
        "metadata": {"data_source": "SYNTHETIC_MVP"},
    },
]

# Text that may appear in a retrieval failure and must stay in the log.
SENSITIVE_DETAILS = [
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "Missing Azure embedding configuration",
    "vector_store",
    "private-store",
    "example-resource.openai.azure.com",
    "connection refused",
    "RAGRetrievalError",
    "RuntimeError",
    "Traceback",
]

# Citations the placeholder briefing used to return for every shipment.
PLACEHOLDER_CITATIONS = ["SOP-04", "SOP-12"]


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(routes_agent.router)
    return TestClient(app)


def use_retrieval(monkeypatch, retrieve) -> None:
    monkeypatch.setattr(
        briefing_service,
        "retrieve_operational_knowledge",
        retrieve,
    )


def fail_retrieval(monkeypatch, error: Exception) -> None:
    def unavailable(query, k=5):
        raise error

    use_retrieval(monkeypatch, unavailable)


def use_real_retrieval(monkeypatch) -> None:
    """Undo the offline mock so the real retrieval code runs."""
    use_retrieval(monkeypatch, rag.retrieval.retrieve_operational_knowledge)


def forbid_azure(monkeypatch) -> list:
    """Fail the test if Azure OpenAI is asked to write the briefing."""
    calls = []

    def must_not_run(**kwargs):
        calls.append(kwargs)
        raise AssertionError("Azure OpenAI must not be called")

    monkeypatch.setattr(briefing_service, "generate_azure_briefing", must_not_run)
    return calls


def remove_azure_configuration(monkeypatch) -> None:
    for name in (
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
        "AZURE_OPENAI_DEPLOYMENT_NAME",
    ):
        monkeypatch.delenv(name, raising=False)


def make_briefing(evidence: ToolEvidence = EVIDENCE) -> DisruptionBriefingResponse:
    return generate_rag_briefing(
        shipment_id="SHP-153440",
        risk_level=RiskLevel.HIGH,
        delay_probability=0.82,
        evidence=evidence,
    )


def stream_done(client) -> dict:
    blocks = client.get(f"{INVESTIGATE_URL}/stream").text.split("\n\n")[:-1]
    event, data = blocks[-1].split("\n")
    assert event == "event: done"
    return json.loads(data.removeprefix("data: "))


def assert_evidence_only_briefing(briefing: DisruptionBriefingResponse) -> None:
    """A briefing built from collected evidence, citing nothing."""
    assert briefing.rag_policy_citations == []
    assert briefing.summary.startswith(
        "Shipment SHP-153440, containing 2 x Trail Running Shoe, has a "
        "HIGH predicted delay risk of 82.0%."
    )
    for collected in (
        EVIDENCE.historical_delay_summary,
        EVIDENCE.weather_summary,
        EVIDENCE.inventory_summary,
    ):
        assert collected in briefing.summary
    assert briefing.recommended_actions
    assert briefing.recommended_actions[0] == (
        "Escalate the shipment for immediate human operational review."
    )

    text = briefing.model_dump_json()
    for placeholder in PLACEHOLDER_CITATIONS:
        assert placeholder not in text
    # Nothing claims that procedures were retrieved or reviewed.
    assert ".pdf" not in text
    assert "Retrieved synthetic operational guidance" not in text
    assert not any(
        "retrieved" in action.lower() for action in briefing.recommended_actions
    )


# ============================================================
# MISSING AZURE CONFIGURATION
# ============================================================


def test_missing_azure_configuration_returns_an_evidence_only_briefing(
    shipment_data,
    monkeypatch,
):
    remove_azure_configuration(monkeypatch)
    use_real_retrieval(monkeypatch)
    azure_calls = forbid_azure(monkeypatch)

    briefing = make_briefing()

    assert_evidence_only_briefing(briefing)
    assert briefing.limitations == [RETRIEVAL_UNAVAILABLE_LIMITATION]
    assert (
        "Supporting operational guidance could not be retrieved, so no "
        "procedures are cited."
        in briefing.summary
    )
    assert azure_calls == []


def test_missing_azure_configuration_does_not_fail_the_investigation(
    client,
    high_risk,
    monkeypatch,
):
    remove_azure_configuration(monkeypatch)
    use_real_retrieval(monkeypatch)
    forbid_azure(monkeypatch)

    response = client.post(INVESTIGATE_URL)

    assert response.status_code == 200
    body = response.json()
    DisruptionBriefingResponse.model_validate(body)
    assert body["rag_policy_citations"] == []
    # Every evidence step still ran and reached the briefing.
    assert [call["status"] for call in body["tool_trace"]] == ["success"] * 6
    assert body["evidence"]["inventory_summary"] in body["summary"]
    assert body["evidence"]["weather_summary"] in body["summary"]
    # Evidence notes, then the briefing's own, then the standing notes.
    assert body["limitations"] == [
        INVENTORY_SCOPE_LIMITATION,
        SUPPLIER_SCOPE_LIMITATION,
        RETRIEVAL_UNAVAILABLE_LIMITATION,
        WEATHER_SCOPE_LIMITATION,
        *UNCOLLECTED_EVIDENCE_LIMITATIONS,
    ]
    for detail in SENSITIVE_DETAILS:
        assert detail not in response.text, detail


def test_stream_completes_and_matches_the_response_without_configuration(
    client,
    high_risk,
    monkeypatch,
):
    remove_azure_configuration(monkeypatch)
    use_real_retrieval(monkeypatch)
    forbid_azure(monkeypatch)

    stream_text = client.get(f"{INVESTIGATE_URL}/stream").text
    done = stream_done(client)

    assert "event: error" not in stream_text
    assert done["rag_policy_citations"] == []
    assert RETRIEVAL_UNAVAILABLE_LIMITATION in done["limitations"]
    assert done == client.post(INVESTIGATE_URL).json()
    for detail in SENSITIVE_DETAILS:
        assert detail not in stream_text, detail


# ============================================================
# UNAVAILABLE VECTOR STORE AND RETRIEVAL FAILURES
# ============================================================


def test_missing_vector_store_returns_an_evidence_only_briefing(
    shipment_data,
    monkeypatch,
    tmp_path,
):
    missing = tmp_path / "private-store" / "vector_store"
    monkeypatch.setattr(rag.retrieval, "VECTOR_STORE_DIRECTORY", missing)
    use_real_retrieval(monkeypatch)
    forbid_azure(monkeypatch)

    briefing = make_briefing()

    assert_evidence_only_briefing(briefing)
    assert briefing.limitations == [RETRIEVAL_UNAVAILABLE_LIMITATION]
    text = briefing.model_dump_json()
    assert "private-store" not in text
    assert tmp_path.name not in text


@pytest.mark.parametrize(
    "error",
    [
        RAGRetrievalError(
            "Operational knowledge retrieval failed: connection refused "
            "by https://example-resource.openai.azure.com"
        ),
        RuntimeError(
            "Missing Azure embedding configuration: AZURE_OPENAI_API_KEY"
        ),
        # Not a retrieval error at all: a defect in a client library.
        KeyError("vector_store"),
        TimeoutError("connection refused"),
    ],
    ids=lambda error: type(error).__name__,
)
def test_retrieval_exception_returns_an_evidence_only_briefing(
    client,
    high_risk,
    monkeypatch,
    error,
):
    fail_retrieval(monkeypatch, error)
    azure_calls = forbid_azure(monkeypatch)

    assert_evidence_only_briefing(make_briefing())

    response = client.post(INVESTIGATE_URL)

    assert response.status_code == 200
    assert response.json()["rag_policy_citations"] == []
    assert RETRIEVAL_UNAVAILABLE_LIMITATION in response.json()["limitations"]
    for detail in SENSITIVE_DETAILS:
        assert detail not in response.text, detail
    assert azure_calls == []


def test_retrieval_failure_is_logged_for_operators(
    shipment_data,
    monkeypatch,
    caplog,
):
    fail_retrieval(
        monkeypatch,
        RAGRetrievalError("The RAG vector store does not exist at '/srv/store'."),
    )

    with caplog.at_level(logging.WARNING, logger=briefing_service.logger.name):
        make_briefing()

    assert "Supporting document retrieval was unavailable" in caplog.text
    assert "/srv/store" in caplog.text


# ============================================================
# EMPTY RETRIEVAL RESULTS
# ============================================================


def test_empty_retrieval_result_returns_an_evidence_only_briefing(
    shipment_data,
    monkeypatch,
):
    use_retrieval(monkeypatch, lambda query, k=5: [])
    azure_calls = forbid_azure(monkeypatch)

    briefing = make_briefing()

    assert_evidence_only_briefing(briefing)
    # The search ran, so the briefing does not say it was unavailable.
    assert briefing.limitations == [NO_DOCUMENTS_RETRIEVED_LIMITATION]
    assert (
        "No relevant operational guidance was retrieved from the "
        "knowledge base."
        in briefing.summary
    )
    assert azure_calls == []


def test_results_without_a_source_are_not_cited(shipment_data, monkeypatch):
    unsourced = [
        {"rank": 1, "source": "", "content": "Reroute immediately."},
        {"rank": 2, "content": "Switch supplier."},
    ]
    use_retrieval(monkeypatch, lambda query, k=5: unsourced)
    forbid_azure(monkeypatch)

    briefing = make_briefing()

    assert_evidence_only_briefing(briefing)
    assert briefing.limitations == [NO_DOCUMENTS_RETRIEVED_LIMITATION]
    # Guidance that cannot be cited is not passed off as guidance.
    assert "Reroute immediately." not in briefing.model_dump_json()
    assert "Switch supplier." not in briefing.model_dump_json()


def test_empty_retrieval_result_does_not_fail_the_investigation(
    client,
    high_risk,
    monkeypatch,
):
    use_retrieval(monkeypatch, lambda query, k=5: [])
    forbid_azure(monkeypatch)

    response = client.post(INVESTIGATE_URL)

    assert response.status_code == 200
    assert response.json()["rag_policy_citations"] == []
    assert NO_DOCUMENTS_RETRIEVED_LIMITATION in response.json()["limitations"]
    assert RETRIEVAL_UNAVAILABLE_LIMITATION not in response.json()["limitations"]


# ============================================================
# SUCCESSFUL RETRIEVAL
# ============================================================


def test_successful_retrieval_cites_exactly_the_retrieved_sources(
    shipment_data,
    monkeypatch,
):
    queries = []
    azure_inputs = []

    def retrieve(query, k=5):
        queries.append((query, k))
        return RETRIEVED

    def azure_briefing(**kwargs):
        azure_inputs.append(kwargs)
        return LLMBriefingContent(
            summary="Grounded summary from the language model.",
            risk_factors=["Historical delay rates: product 57.0%."],
            recommended_actions=["Escalate for human review."],
        )

    use_retrieval(monkeypatch, retrieve)
    monkeypatch.setattr(briefing_service, "generate_azure_briefing", azure_briefing)

    briefing = make_briefing()

    # Each retrieved source once, in retrieval order, and nothing else.
    assert briefing.rag_policy_citations == [
        "01_shipment_delay_escalation.pdf",
        "04_inventory_stockout_response.pdf",
    ]
    assert briefing.summary == "Grounded summary from the language model."
    assert briefing.recommended_actions == ["Escalate for human review."]
    assert briefing.limitations == []

    # The search is driven by the collected evidence, and the language
    # model is given the documents that were retrieved.
    assert len(queries) == 1
    assert EVIDENCE.inventory_summary in queries[0][0]
    assert queries[0][1] == 5
    assert azure_inputs[0]["retrieved_knowledge"] == RETRIEVED
    assert azure_inputs[0]["evidence"] == EVIDENCE


def test_successful_retrieval_keeps_the_investigation_limitations_unchanged(
    high_risk,
):
    # The offline mock retrieves three documents and writes the briefing.
    briefing = run_investigation("SHP-153440")

    assert briefing.rag_policy_citations == [
        "01_shipment_delay_escalation.pdf",
        "02_weather_disruption_sop.pdf",
        "03_supplier_alternative_policy.pdf",
    ]
    assert briefing.limitations == [
        INVENTORY_SCOPE_LIMITATION,
        SUPPLIER_SCOPE_LIMITATION,
        WEATHER_SCOPE_LIMITATION,
        *UNCOLLECTED_EVIDENCE_LIMITATIONS,
    ]


def test_azure_failure_keeps_retrieved_citations_and_says_how_it_was_written(
    shipment_data,
    monkeypatch,
):
    def azure_outage(**kwargs):
        raise AzureOpenAIServiceError(
            "Azure OpenAI request to "
            "https://example-resource.openai.azure.com failed."
        )

    use_retrieval(monkeypatch, lambda query, k=5: RETRIEVED)
    monkeypatch.setattr(briefing_service, "generate_azure_briefing", azure_outage)

    briefing = make_briefing()

    # Retrieval succeeded, so its sources are still cited.
    assert briefing.rag_policy_citations == [
        "01_shipment_delay_escalation.pdf",
        "04_inventory_stockout_response.pdf",
    ]
    assert briefing.limitations == [DETERMINISTIC_BRIEFING_LIMITATION]
    assert "01_shipment_delay_escalation.pdf:" in briefing.summary
    assert EVIDENCE.weather_summary in briefing.summary
    assert "example-resource.openai.azure.com" not in briefing.model_dump_json()


# ============================================================
# WHAT STILL ENDS THE INVESTIGATION
# ============================================================


def test_low_risk_shipment_is_still_rejected_without_retrieval(
    client,
    low_risk,
    monkeypatch,
):
    fail_retrieval(monkeypatch, RAGRetrievalError("vector_store missing"))

    response = client.post(INVESTIGATE_URL)

    assert response.status_code == 400
    assert "LOW risk" in response.json()["detail"]


def test_inventory_and_retrieval_failures_together_still_return_a_briefing(
    client,
    high_risk,
    monkeypatch,
):
    def no_inventory(shipment):
        raise RuntimeError("inventory dataset unavailable")

    monkeypatch.setattr(agent_service, "get_inventory_coverage", no_inventory)
    fail_retrieval(monkeypatch, RAGRetrievalError("vector_store missing"))
    forbid_azure(monkeypatch)

    response = client.post(INVESTIGATE_URL)

    assert response.status_code == 200
    body = response.json()
    assert body["rag_policy_citations"] == []
    assert body["evidence"]["inventory_summary"] is None
    assert body["evidence"]["weather_summary"] in body["summary"]
    assert body["limitations"] == [
        "Inventory evidence was not collected: "
        "No inventory record could be retrieved for this product.",
        SUPPLIER_SCOPE_LIMITATION,
        RETRIEVAL_UNAVAILABLE_LIMITATION,
        WEATHER_SCOPE_LIMITATION,
        *UNCOLLECTED_EVIDENCE_LIMITATIONS,
    ]
