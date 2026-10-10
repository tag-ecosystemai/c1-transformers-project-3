from backend.models.schemas import RiskLevel, ToolEvidence
from backend.services.briefing_service import generate_rag_briefing


def make_briefing(evidence, probability=0.55):
    return generate_rag_briefing(
        shipment_id="SHP-153440",
        risk_level=RiskLevel.MEDIUM,
        delay_probability=probability,
        evidence=evidence,
    )


def test_summary_formats_probability_as_clean_percentage(shipment_data):
    briefing = make_briefing(ToolEvidence(), probability=0.55)

    assert "MEDIUM risk (55.0%)" in briefing.summary
    assert "55.00000000000001" not in briefing.summary


def test_summary_omits_evidence_that_was_not_collected(shipment_data):
    briefing = make_briefing(ToolEvidence())

    assert briefing.summary == (
        "Shipment SHP-153440 (Cleats bound for Vassouras, Brasil) faces a "
        "MEDIUM risk (55.0%). RAG policy suggests immediate intervention."
    )
    assert "None" not in briefing.summary
    assert all("None" not in action for action in briefing.recommended_actions)


def test_summary_includes_collected_evidence(shipment_data):
    evidence = ToolEvidence(
        weather_summary="Heavy rain at the destination.",
        historical_delay_summary="Historical delay rates: product 57.0%.",
        inventory_coverage_days=12,
    )

    briefing = make_briefing(evidence)

    assert briefing.summary.endswith(
        "intervention based on environmental evidence: Heavy rain at the "
        "destination. Historical delay rates: product 57.0%."
    )
    assert "inventory buffer of 12 days" in briefing.recommended_actions[1]


def test_inventory_action_without_a_record_says_coverage_is_unavailable(
    shipment_data,
):
    action = make_briefing(ToolEvidence()).recommended_actions[1]

    assert "inventory coverage not yet available" in action


def test_inventory_action_with_a_record_asks_for_shipment_confirmation(
    shipment_data,
):
    evidence = ToolEvidence(
        inventory_summary="Inventory record for 'Trail Running Shoe'."
    )

    action = make_briefing(evidence).recommended_actions[1]

    # A product-level record is not a buffer this shipment can rely on.
    assert action == (
        "Trigger SOP-12: Review the inventory record and confirm that "
        "stock is available for this shipment before relying on an "
        "inventory buffer."
    )
    assert "not yet available" not in action
