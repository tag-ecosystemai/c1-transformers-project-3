from pathlib import Path

import pytest

from backend.exceptions import (
    AzureOpenAIServiceError,
)
from backend.models.schemas import (
    LLMBriefingContent,
    RiskLevel,
    ToolEvidence,
)
from backend.services import briefing_service
from backend.services.briefing_service import (
    generate_rag_briefing,
)


@pytest.fixture(autouse=True)
def mock_external_briefing_dependencies(
    monkeypatch,
):
    """
    Mock RAG retrieval and Azure OpenAI synthesis.

    These tests verify briefing-service behavior without making real
    Azure requests or depending on Chroma retrieval ranking.
    """
    retrieved_documents = [
        {
            "rank": 1,
            "source": (
                "01_shipment_delay_escalation.pdf"
            ),
            "source_path": (
                "01_shipment_delay_escalation.pdf"
            ),
            "relevance_score": 0.91,
            "content": (
                "Medium-risk shipments require investigation and "
                "collection of available operational evidence."
            ),
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
            "relevance_score": 0.84,
            "content": (
                "Low-severity destination weather does not "
                "independently justify shipment rerouting."
            ),
            "metadata": {
                "data_source": "SYNTHETIC_MVP",
            },
        },
    ]

    monkeypatch.setattr(
        briefing_service,
        "retrieve_operational_knowledge",
        lambda query, k=5: retrieved_documents,
    )

    def mock_generate_azure_briefing(
        shipment_id,
        risk_level,
        delay_probability,
        evidence,
        retrieved_knowledge,
    ):
        """
        Return deterministic Azure-style structured content.
        """
        summary_parts = [
            (
                f"Shipment {shipment_id} has a "
                f"{risk_level.value} predicted delay risk of "
                f"{delay_probability:.1%}."
            )
        ]

        risk_factors = []

        if evidence.shipment_summary:
            summary_parts.append(
                evidence.shipment_summary
            )

        if evidence.historical_delay_summary:
            summary_parts.append(
                evidence.historical_delay_summary
            )

            risk_factors.append(
                evidence.historical_delay_summary
            )

        if evidence.weather_summary:
            summary_parts.append(
                evidence.weather_summary
            )

            risk_factors.append(
                evidence.weather_summary
            )

        if evidence.supplier_status:
            summary_parts.append(
                evidence.supplier_status
            )

            risk_factors.append(
                evidence.supplier_status
            )
        else:
            summary_parts.append(
                "Supplier availability has not yet been assessed."
            )

        if evidence.inventory_coverage_days is not None:
            summary_parts.append(
                "Available inventory coverage is "
                f"{evidence.inventory_coverage_days} days."
            )
        else:
            summary_parts.append(
                "Inventory coverage has not yet been assessed."
            )

        recommended_actions = [
            "Continue human operational review.",
        ]

        if evidence.historical_delay_summary:
            recommended_actions.append(
                "Review the elevated historical delay factors."
            )

        if evidence.weather_summary:
            weather_text = (
                evidence.weather_summary.lower()
            )

            severe_weather_terms = (
                "high severity",
                "severe weather",
                "thunderstorm",
                "heavy rain",
                "heavy snow",
                "extreme weather",
                "flood",
                "hurricane",
                "tornado",
            )

            low_weather_terms = (
                "low severity",
                "light drizzle",
                "clear sky",
                "mainly clear",
                "partly cloudy",
            )

            severe_weather = any(
                term in weather_text
                for term in severe_weather_terms
            )

            low_weather = any(
                term in weather_text
                for term in low_weather_terms
            )

            if severe_weather and not low_weather:
                recommended_actions.append(
                    "Evaluate transport alternatives because the "
                    "collected weather evidence indicates potentially "
                    "severe conditions."
                )

            elif low_weather:
                recommended_actions.append(
                    "Continue monitoring destination weather, but do "
                    "not reroute solely on the current low-severity "
                    "weather evidence."
                )

            else:
                recommended_actions.append(
                    "Continue monitoring destination weather before "
                    "making any rerouting decision."
                )

        if evidence.supplier_status:
            recommended_actions.append(
                "Validate the synthetic supplier geographically, "
                "commercially, and operationally before considering "
                "a supplier change."
            )
        else:
            recommended_actions.append(
                "Obtain supplier availability and performance "
                "evidence before recommending an alternative."
            )

        if evidence.inventory_coverage_days is None:
            recommended_actions.append(
                "Obtain inventory coverage before determining "
                "stockout exposure."
            )

        elif evidence.inventory_coverage_days <= 3:
            recommended_actions.append(
                "Escalate potential stockout exposure because "
                "inventory coverage is three days or less."
            )

        else:
            recommended_actions.append(
                "Compare the expected disruption duration with "
                "available inventory coverage."
            )

        return LLMBriefingContent(
            summary=" ".join(summary_parts),
            risk_factors=risk_factors,
            recommended_actions=recommended_actions,
        )

    monkeypatch.setattr(
        briefing_service,
        "generate_azure_briefing",
        mock_generate_azure_briefing,
    )

INVENTORY_SUMMARY = (
    "Inventory record for 'Trail Running Shoe': 428 units available "
    "(453 in stock, 25 reserved) against average demand of 109 units "
    "per day, about 3.93 days of coverage. Available stock is at or "
    "below the safety-stock level of 572 units. No incoming "
    "replenishment is recorded. Stockout risk on record: HIGH. This is "
    "a product-level record; stock availability for this shipment has "
    "not been verified."
)


def make_inventory_evidence() -> ToolEvidence:
    """
    Inventory evidence as the investigation provides it: a summary of
    the product-level record, with no whole-day coverage figure.
    """
    return ToolEvidence(
        inventory_summary=INVENTORY_SUMMARY,
    )

def make_briefing(
    evidence: ToolEvidence,
    probability: float = 0.55,
):
    """
    Generate a briefing using the mocked external dependencies.
    """
    return generate_rag_briefing(
        shipment_id="SHP-153440",
        risk_level=RiskLevel.MEDIUM,
        delay_probability=probability,
        evidence=evidence,
    )

def test_rag_query_contains_the_inventory_record_summary():
    query = briefing_service.build_rag_query(
        shipment_id="SHP-153444",
        risk_level=RiskLevel.HIGH,
        delay_probability=0.82,
        evidence=make_inventory_evidence(),
    )

    assert (
        f"Inventory evidence (product-level record): {INVENTORY_SUMMARY}"
        in query
    )
    assert "about 3.93 days of coverage" in query
    assert (
        "Stock availability for this shipment has not been verified."
        in query
    )
    assert "Inventory coverage is not currently available." not in query
    assert (
        "Delay probability is not a prediction "
        "of the number of delay days."
        in query
    )


def test_rag_query_makes_no_warehouse_or_destination_match_claim():
    query = briefing_service.build_rag_query(
        shipment_id="SHP-153444",
        risk_level=RiskLevel.HIGH,
        delay_probability=0.82,
        evidence=make_inventory_evidence(),
    ).lower()

    for claim in ("warehouse", "reorder point", "matches shipment destination"):
        assert claim not in query, claim


def test_rag_query_reports_missing_inventory_evidence():
    query = briefing_service.build_rag_query(
        shipment_id="SHP-153444",
        risk_level=RiskLevel.HIGH,
        delay_probability=0.82,
        evidence=ToolEvidence(),
    )

    assert "Inventory coverage is not currently available." in query


def test_inventory_record_asks_for_shipment_level_confirmation():
    actions = (
        briefing_service
        .build_deterministic_actions(
            risk_level=RiskLevel.HIGH,
            evidence=make_inventory_evidence(),
            retrieved_knowledge=[],
        )
    )

    assert (
        "Review the product-level inventory record and confirm that "
        "stock is available for this shipment before relying on "
        "inventory as mitigation."
        in actions
    )
    # A product-level record supports no warehouse or transfer advice.
    assert not any(
        claim in action.lower()
        for action in actions
        for claim in ("warehouse", "reorder point", "destination country")
    )


def test_missing_inventory_evidence_asks_for_inventory_coverage():
    actions = (
        briefing_service
        .build_deterministic_actions(
            risk_level=RiskLevel.HIGH,
            evidence=ToolEvidence(),
            retrieved_knowledge=[],
        )
    )

    assert any(
        "obtain current inventory coverage" in action.lower()
        for action in actions
    )


def test_summary_formats_probability_as_clean_percentage(
    shipment_data,
):
    briefing = make_briefing(
        ToolEvidence(),
        probability=0.55,
    )

    assert (
        "MEDIUM predicted delay risk of 55.0%"
        in briefing.summary
    )

    assert briefing.delay_probability == 0.55
    assert briefing.risk_level == RiskLevel.MEDIUM


def test_summary_reports_unavailable_evidence(
    shipment_data,
):
    briefing = make_briefing(
        ToolEvidence()
    )

    assert (
        "Supplier availability has not yet "
        "been assessed."
        in briefing.summary
    )

    assert (
        "Inventory coverage has not yet "
        "been assessed."
        in briefing.summary
    )

    assert (
        "environmental evidence"
        not in briefing.summary
    )

    assert (
        "RAG policy suggests immediate intervention"
        not in briefing.summary
    )


def test_summary_includes_collected_evidence(
    shipment_data,
):
    evidence = ToolEvidence(
        weather_summary=(
            "Heavy rain at the destination."
        ),
        historical_delay_summary=(
            "Historical delay rates: "
            "product 57.0%."
        ),
        inventory_coverage_days=12,
    )

    briefing = make_briefing(
        evidence
    )

    assert (
        "Heavy rain at the destination."
        in briefing.summary
    )

    assert (
        "Historical delay rates: "
        "product 57.0%."
        in briefing.summary
    )

    assert (
        "Available inventory coverage is "
        "12 days."
        in briefing.summary
    )


def test_briefing_returns_real_pdf_citations(
    shipment_data,
):
    briefing = make_briefing(
        ToolEvidence()
    )

    assert briefing.rag_policy_citations

    available_documents = {
        path.name
        for path in Path(
            "rag/documents"
        ).glob("*.pdf")
    }

    assert set(
        briefing.rag_policy_citations
    ).issubset(
        available_documents
    )


def test_briefing_does_not_return_placeholder_sops(
    shipment_data,
):
    briefing = make_briefing(
        ToolEvidence()
    )

    placeholder_citations = {
        (
            "SOP-04: Extreme Weather "
            "Rerouting Protocol"
        ),
        (
            "SOP-12: Inventory Buffer "
            "Utilization for High-Risk "
            "Categories"
        ),
    }

    assert not (
        placeholder_citations
        & set(briefing.rag_policy_citations)
    )


def test_low_severity_weather_does_not_trigger_rerouting(
    shipment_data,
):
    evidence = ToolEvidence(
        weather_summary=(
            "Observed destination weather showed "
            "light drizzle with low severity."
        ),
    )

    briefing = make_briefing(
        evidence
    )

    assert any(
        (
            "do not reroute solely"
            in action.lower()
        )
        for action in briefing.recommended_actions
    )

    assert not any(
        (
            "reroute via secondary transit hub "
            "immediately"
            in action.lower()
        )
        for action in briefing.recommended_actions
    )


def test_severe_weather_supports_transport_review(
    shipment_data,
):
    evidence = ToolEvidence(
        weather_summary=(
            "Observed destination weather showed "
            "heavy rain with high severity."
        ),
    )

    briefing = make_briefing(
        evidence
    )

    assert any(
        (
            "evaluate transport alternatives"
            in action.lower()
        )
        for action in briefing.recommended_actions
    )


def test_supplier_evidence_requires_validation(
    shipment_data,
):
    evidence = ToolEvidence(
        supplier_status=(
            "Synthetic supplier SUP003 has MEDIUM risk, "
            "but geographic suitability is unverified."
        ),
    )

    briefing = make_briefing(
        evidence
    )

    assert (
        evidence.supplier_status
        in briefing.summary
    )

    assert any(
        (
            "validate the synthetic supplier"
            in action.lower()
        )
        for action in briefing.recommended_actions
    )


def test_azure_failure_uses_deterministic_fallback(
    shipment_data,
    monkeypatch,
):
    def broken_azure_generation(**kwargs):
        raise AzureOpenAIServiceError(
            "simulated Azure outage"
        )

    monkeypatch.setattr(
        briefing_service,
        "generate_azure_briefing",
        broken_azure_generation,
    )

    evidence = ToolEvidence(
        historical_delay_summary=(
            "Historical product delay rate is elevated."
        ),
        weather_summary=(
            "Destination weather has low severity."
        ),
        supplier_status=(
            "Synthetic supplier evidence requires "
            "human validation."
        ),
        inventory_coverage_days=None,
    )

    briefing = make_briefing(
        evidence
    )

    assert briefing.summary

    assert (
        "Historical product delay rate is elevated."
        in briefing.summary
    )

    assert (
        "Destination weather has low severity."
        in briefing.summary
    )

    assert briefing.recommended_actions

    assert any(
        (
            "human"
            in action.lower()
            or "monitor"
            in action.lower()
        )
        for action in briefing.recommended_actions
    )
