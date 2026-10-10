import json
from types import SimpleNamespace
from datetime import date

import pytest

from backend.exceptions import (
    AzureOpenAIServiceError,
)
from backend.models.schemas import (
    RiskLevel,
    ToolEvidence,
)
from backend.services import azure_openai_service


@pytest.fixture(autouse=True)
def clear_client_cache():
    azure_openai_service.clear_azure_openai_client_cache()

    yield

    azure_openai_service.clear_azure_openai_client_cache()


@pytest.fixture
def evidence():
    return ToolEvidence(
        shipment_summary=(
            "SHP-153444: 1 x Perfect Fitness Perfect Rip Deck "
            "to Indaial, Brasil by Standard Class."
        ),
        historical_delay_summary=(
            "Historical delay rates: product 55.0%, "
            "market 54.3%, shipping mode 38.1%."
        ),
        weather_summary=(
            "Observed destination weather showed light drizzle "
            "with low severity."
        ),
        supplier_status=(
            "Synthetic supplier candidate SUP003 is located in "
            "Bhutan and has MEDIUM risk. Geographic suitability "
            "for Brazil has not been verified."
        ),
        inventory_coverage_days=None,
    )

INVENTORY_SUMMARY = (
    "Inventory record for 'Perfect Fitness Perfect Rip Deck': 428 "
    "units available (453 in stock, 25 reserved) against average "
    "demand of 109 units per day, about 3.93 days of coverage. "
    "Available stock is at or below the safety-stock level of 572 "
    "units. No incoming replenishment is recorded. Stockout risk on "
    "record: HIGH. This is a product-level record; stock availability "
    "for this shipment has not been verified."
)


@pytest.fixture
def inventory_evidence():
    """
    Inventory evidence as the investigation provides it: the summary
    of a product-level record, with no whole-day coverage figure.
    """
    return ToolEvidence(
        shipment_summary=(
            "SHP-153444: 1 x Perfect Fitness Perfect Rip Deck "
            "to Indaial, Brasil by Standard Class."
        ),
        inventory_summary=INVENTORY_SUMMARY,
    )

@pytest.fixture
def retrieved_knowledge():
    return [
        {
            "rank": 1,
            "source": (
                "01_shipment_delay_escalation.pdf"
            ),
            "source_path": (
                "01_shipment_delay_escalation.pdf"
            ),
            "content": (
                "Medium-risk shipments require investigation "
                "and collection of available evidence."
            ),
            "relevance_score": 0.91,
            "metadata": {
                "data_source": "SYNTHETIC_MVP",
            },
        },
        {
            "rank": 2,
            "source": (
                "02_weather_disruption_sop.pdf"
            ),
            "source_path": (
                "02_weather_disruption_sop.pdf"
            ),
            "content": (
                "Low-severity weather does not independently "
                "justify immediate rerouting."
            ),
            "relevance_score": 0.84,
            "metadata": {
                "data_source": "SYNTHETIC_MVP",
            },
        },
    ]


def make_mock_client(
    response_content: str,
):
    message = SimpleNamespace(
        content=response_content
    )

    choice = SimpleNamespace(
        message=message
    )

    response = SimpleNamespace(
        choices=[choice]
    )

    completions = SimpleNamespace(
        create=lambda **kwargs: response
    )

    chat = SimpleNamespace(
        completions=completions
    )

    return SimpleNamespace(
        chat=chat
    )

def test_build_llm_input_contains_the_inventory_record_summary(
    inventory_evidence,
    retrieved_knowledge,
):
    result = (
        azure_openai_service
        .build_llm_input(
            shipment_id="SHP-153444",
            risk_level=RiskLevel.HIGH,
            delay_probability=0.82,
            evidence=inventory_evidence,
            retrieved_knowledge=(
                retrieved_knowledge
            ),
        )
    )

    payload = json.loads(
        result
    )

    collected = payload[
        "collected_evidence"
    ]

    # The inventory record reaches Azure exactly as the investigation
    # summarized it, with every figure it was given.
    assert (
        collected["inventory_summary"]
        == INVENTORY_SUMMARY
    )

    inventory = collected[
        "inventory_summary"
    ]

    assert (
        "428 units available"
        in inventory
    )

    assert (
        "average demand of 109 units per day"
        in inventory
    )

    assert (
        "about 3.93 days of coverage"
        in inventory
    )

    assert (
        "Stockout risk on record: HIGH"
        in inventory
    )

    assert (
        "at or below the safety-stock level of 572 units"
        in inventory
    )

    assert (
        "No incoming replenishment is recorded"
        in inventory
    )

    assert (
        "stock availability for this shipment has not been verified"
        in inventory
    )

    # Fractional coverage is not rounded into the whole-day field.
    assert (
        collected["inventory_coverage_days"]
        is None
    )

    # Nothing shipment-specific is claimed about the record: no nested
    # record, warehouse, reorder point or destination match is sent.
    assert (
        "inventory_status"
        not in collected
    )

    collected_text = json.dumps(
        collected
    )

    for claim in (
        "warehouse",
        "reorder_point",
        "destination_country_match",
        "calculation_verified",
    ):
        assert claim not in collected_text, claim

    assert (
        payload["shipment"][
            "delay_duration_days"
        ]
        is None
    )

    assert (
        payload["shipment"][
            "delay_duration_available"
        ]
        is False
    )

def test_build_llm_input_contains_grounded_evidence(
    evidence,
    retrieved_knowledge,
):
    result = azure_openai_service.build_llm_input(
        shipment_id="SHP-153444",
        risk_level=RiskLevel.MEDIUM,
        delay_probability=0.4033,
        evidence=evidence,
        retrieved_knowledge=retrieved_knowledge,
    )

    payload = json.loads(result)

    assert (
        payload["shipment"]["shipment_id"]
        == "SHP-153444"
    )

    assert (
        payload["shipment"]["risk_level"]
        == "MEDIUM"
    )

    assert (
        payload["shipment"]["delay_probability"]
        == 0.4033
    )

    assert (
        payload["collected_evidence"]["weather_summary"]
        == evidence.weather_summary
    )

    assert (
        payload["collected_evidence"]["supplier_status"]
        == evidence.supplier_status
    )

    assert (
        payload[
            "collected_evidence"
        ]["inventory_coverage_days"]
        is None
    )

    assert (
        payload[
            "retrieved_operational_guidance"
        ][0]["source"]
        == "01_shipment_delay_escalation.pdf"
    )

    assert (
        payload[
            "retrieved_operational_guidance"
        ][0]["data_source"]
        == "SYNTHETIC_MVP"
    )


def test_parse_valid_llm_response():
    content = json.dumps(
        {
            "summary": (
                "The shipment requires active monitoring."
            ),
            "risk_factors": [
                "Historical product delay rate is elevated.",
            ],
            "recommended_actions": [
                "Continue monitoring the shipment.",
            ],
        }
    )

    result = (
        azure_openai_service
        .parse_llm_response(content)
    )

    assert result.summary == (
        "The shipment requires active monitoring."
    )

    assert result.risk_factors == [
        "Historical product delay rate is elevated.",
    ]

    assert result.recommended_actions == [
        "Continue monitoring the shipment.",
    ]


def test_parse_empty_response_raises():
    with pytest.raises(
        AzureOpenAIServiceError,
        match="empty briefing response",
    ):
        azure_openai_service.parse_llm_response(
            ""
        )


def test_parse_invalid_json_raises():
    with pytest.raises(
        AzureOpenAIServiceError,
        match="invalid JSON",
    ):
        azure_openai_service.parse_llm_response(
            "This is not JSON."
        )


def test_parse_wrong_schema_raises():
    content = json.dumps(
        {
            "risk_factors": [],
            "recommended_actions": [],
        }
    )

    with pytest.raises(
        AzureOpenAIServiceError,
        match="does not match the briefing schema",
    ):
        azure_openai_service.parse_llm_response(
            content
        )


def test_generate_azure_briefing_returns_structured_content(
    evidence,
    retrieved_knowledge,
    monkeypatch,
):
    response_content = json.dumps(
        {
            "summary": (
                "Shipment SHP-153444 requires active monitoring."
            ),
            "risk_factors": [
                (
                    "Historical product and market delay rates "
                    "are elevated."
                ),
                (
                    "Supplier geographic suitability is "
                    "not verified."
                ),
            ],
            "recommended_actions": [
                "Continue monitoring the shipment.",
                (
                    "Validate the synthetic supplier before "
                    "considering a change."
                ),
                "Obtain inventory coverage.",
            ],
        }
    )

    mock_client = make_mock_client(
        response_content
    )

    monkeypatch.setattr(
        azure_openai_service,
        "get_azure_openai_client",
        lambda: mock_client,
    )

    monkeypatch.setattr(
        azure_openai_service.settings,
        "azure_openai_chat_deployment",
        "logistics-llm",
    )

    result = (
        azure_openai_service
        .generate_azure_briefing(
            shipment_id="SHP-153444",
            risk_level=RiskLevel.MEDIUM,
            delay_probability=0.4033,
            evidence=evidence,
            retrieved_knowledge=(
                retrieved_knowledge
            ),
        )
    )

    assert result.summary == (
        "Shipment SHP-153444 requires active monitoring."
    )

    assert len(result.risk_factors) == 2
    assert len(result.recommended_actions) == 3


def test_generate_requires_retrieved_knowledge(
    evidence,
):
    with pytest.raises(
        AzureOpenAIServiceError,
        match=(
            "requires retrieved operational knowledge"
        ),
    ):
        azure_openai_service.generate_azure_briefing(
            shipment_id="SHP-153444",
            risk_level=RiskLevel.MEDIUM,
            delay_probability=0.4033,
            evidence=evidence,
            retrieved_knowledge=[],
        )


def test_generate_rejects_invalid_probability(
    evidence,
    retrieved_knowledge,
):
    with pytest.raises(
        ValueError,
        match=(
            "Delay probability must be between 0 and 1"
        ),
    ):
        azure_openai_service.generate_azure_briefing(
            shipment_id="SHP-153444",
            risk_level=RiskLevel.MEDIUM,
            delay_probability=1.5,
            evidence=evidence,
            retrieved_knowledge=(
                retrieved_knowledge
            ),
        )


def test_system_prompt_prohibits_invention():
    prompt = " ".join(
        azure_openai_service
        .SYSTEM_PROMPT
        .lower()
        .split()
    )

    assert (
        "do not invent shipment facts"
        in prompt
    )

    assert (
        "do not invent weather conditions"
        in prompt
    )

    assert (
        "do not invent inventory"
        in prompt
    )

    assert (
        "do not invent policy citations"
        in prompt
    )

    assert "synthetic_mvp" in prompt

    assert (
        "does not justify immediate rerouting"
        in prompt
    )

    assert (
        "delay probability"
        in prompt
    )

    assert (
        "not a prediction of delay duration"
        in prompt
    )

    assert (
        "do not claim that a stockout is certain"
        in prompt
    )

    assert (
        "do not treat incoming inventory as guaranteed"
        in prompt
    )

    assert (
        "inventory records"
        in prompt
    )

    assert (
        "synthetic_mvp"
        in prompt
    )

    assert (
        "demonstration data"
        in prompt
    )


def test_system_prompt_describes_summary_based_inventory_evidence():
    prompt = " ".join(
        azure_openai_service
        .SYSTEM_PROMPT
        .lower()
        .split()
    )

    assert (
        "is supplied as inventory_summary"
        in prompt
    )

    assert (
        "product-level inventory record"
        in prompt
    )

    assert (
        "exactly as the summary states them"
        in prompt
    )

    assert (
        "does not verify that stock is available for this shipment"
        in prompt
    )

    assert (
        "do not infer a warehouse, a location, or a replenishment date"
        in prompt
    )

    # The prompt no longer asks for values the evidence does not carry.
    assert (
        "warehouse, and replenishment values exactly"
        not in prompt
    )

    assert (
        "inventory tool evidence"
        not in prompt
    )


def test_prompt_keeps_supplier_candidates_distinct_from_commitments(
    evidence,
    retrieved_knowledge,
):
    prompt = " ".join(
        azure_openai_service
        .SYSTEM_PROMPT
        .lower()
        .split()
    )

    assert (
        "category-level suggestion of an alternative supplier candidate"
        in prompt
    )

    assert (
        "matched on product category only"
        in prompt
    )

    assert (
        "does not verify supplier availability, capacity for the "
        "required quantity, commercial terms, or delivery commitments"
        in prompt
    )

    assert (
        "do not describe a candidate as available, approved, "
        "contracted, or selected"
        in prompt
    )

    # The existing supplier and human-review rules are still there.
    assert (
        "do not invent supplier availability or supplier performance"
        in prompt
    )

    assert (
        "recommend human review before changing suppliers"
        in prompt
    )

    instructions = " ".join(
        json.loads(
            azure_openai_service
            .build_llm_input(
                shipment_id="SHP-153444",
                risk_level=RiskLevel.MEDIUM,
                delay_probability=0.4033,
                evidence=evidence,
                retrieved_knowledge=(
                    retrieved_knowledge
                ),
            )
        )["instructions"]
    )

    assert (
        "Supplier evidence is a category-level candidate suggestion."
        in instructions
    )

    assert (
        "do not present its capacity, commercial terms, or delivery "
        "commitments as verified"
        in instructions
    )


def test_llm_instructions_match_the_inventory_evidence_contract(
    inventory_evidence,
    retrieved_knowledge,
):
    payload = json.loads(
        azure_openai_service
        .build_llm_input(
            shipment_id="SHP-153444",
            risk_level=RiskLevel.HIGH,
            delay_probability=0.82,
            evidence=inventory_evidence,
            retrieved_knowledge=(
                retrieved_knowledge
            ),
        )
    )

    instructions = " ".join(
        payload["instructions"]
    )

    assert (
        "Use the figures in inventory_summary exactly as provided."
        in instructions
    )

    assert (
        "does not verify that stock is available for this shipment"
        in instructions
    )

    assert (
        "structured Inventory Tool values"
        not in instructions
    )

    # Citation grounding is unchanged: only retrieved guidance is
    # supplied, each item with its source.
    assert (
        "Use only the supplied prediction, collected evidence, "
        "and retrieved guidance."
        in instructions
    )

    assert [
        item["source"]
        for item in payload[
            "retrieved_operational_guidance"
        ]
    ] == [
        "01_shipment_delay_escalation.pdf",
        "02_weather_disruption_sop.pdf",
    ]


def test_azure_failure_uses_service_exception(
    evidence,
    retrieved_knowledge,
    monkeypatch,
):
    def raise_azure_error(**kwargs):
        raise RuntimeError(
            "simulated Azure outage"
        )

    completions = SimpleNamespace(
        create=raise_azure_error
    )

    chat = SimpleNamespace(
        completions=completions
    )

    mock_client = SimpleNamespace(
        chat=chat
    )

    monkeypatch.setattr(
        azure_openai_service,
        "get_azure_openai_client",
        lambda: mock_client,
    )

    monkeypatch.setattr(
        azure_openai_service.settings,
        "azure_openai_chat_deployment",
        "logistics-llm",
    )

    with pytest.raises(
        AzureOpenAIServiceError,
        match="briefing generation failed",
    ):
        azure_openai_service.generate_azure_briefing(
            shipment_id="SHP-153444",
            risk_level=RiskLevel.MEDIUM,
            delay_probability=0.4033,
            evidence=evidence,
            retrieved_knowledge=(
                retrieved_knowledge
            ),
        )