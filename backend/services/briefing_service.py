from backend.models.schemas import ToolEvidence, DisruptionBriefingResponse, RiskLevel
from backend.services.shipment_service import get_shipment_by_id

def generate_rag_briefing(shipment_id: str, risk_level: RiskLevel, delay_probability: float, evidence: ToolEvidence) -> DisruptionBriefingResponse:
    """
    Takes the raw evidence found by the AI Agent, queries the RAG ChromaDB for relevant SOPs,
    and uses Azure OpenAI to synthesize a final mitigation briefing.

    RAG retrieval and Azure OpenAI are not yet connected: the SOP citations
    and recommended actions are fixed placeholders, and the summary is a
    template that mentions only the evidence actually collected.
    """
    shipment = get_shipment_by_id(shipment_id)
    
    # --- 1. RAG RETRIEVAL STAGE ---
    # When your ChromaDB is fully populated, you will import your retrieval function here.
    # Example:
    # from backend.rag.retrieval import search_sops
    # rag_query = f"Mitigation for {shipment.product_category} delay. Weather issue: {evidence.weather_summary}"
    # retrieved_sops = search_sops(rag_query)
    
    # Fallback simulation for architectural testing:
    simulated_sops = [
        "SOP-04: Extreme Weather Rerouting Protocol",
        "SOP-12: Inventory Buffer Utilization for High-Risk Categories"
    ]

    # --- 2. LLM SYNTHESIS STAGE ---
    # When Azure OpenAI is active, you will pass the evidence and SOPs into a prompt here.
    # Example:
    # prompt = f"Given SOPs: {simulated_sops}, and Evidence: {evidence}, generate a summary..."
    
    # Fallback LLM generation for architectural testing:
    # Only evidence that was actually collected is mentioned.
    summary = (
        f"Shipment {shipment_id} ({shipment.category} bound for {shipment.destination_city}, {shipment.destination_country}) "
        f"faces a {risk_level.value} risk ({delay_probability:.1%}). RAG policy suggests immediate intervention"
    )
    if evidence.weather_summary:
        summary += f" based on environmental evidence: {evidence.weather_summary}"
    else:
        summary += "."
    if evidence.historical_delay_summary:
        summary += f" {evidence.historical_delay_summary}"

    if evidence.inventory_coverage_days is not None:
        inventory_action = f"Trigger SOP-12: Utilize inventory buffer of {evidence.inventory_coverage_days} days to fulfill active destination orders."
    elif evidence.inventory_summary:
        # The inventory record describes the product, not this shipment.
        inventory_action = "Trigger SOP-12: Review the inventory record and confirm that stock is available for this shipment before relying on an inventory buffer."
    else:
        inventory_action = "Trigger SOP-12: Confirm the available inventory buffer before fulfilling active destination orders (inventory coverage not yet available)."

    recommended_actions = [
        "Trigger SOP-04: Reroute via secondary transit hub immediately.",
        inventory_action,
    ]

    return DisruptionBriefingResponse(
        shipment_id=shipment_id,
        risk_level=risk_level,
        delay_probability=delay_probability,
        evidence=evidence,
        rag_policy_citations=simulated_sops,
        summary=summary,
        recommended_actions=recommended_actions
    )