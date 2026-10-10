import logging
from typing import Any

from backend.exceptions import AzureOpenAIServiceError
from backend.models.schemas import (
    DisruptionBriefingResponse,
    LLMBriefingContent,
    RiskLevel,
    ToolEvidence,
)
from backend.services.azure_openai_service import (
    generate_azure_briefing,
)
from backend.services.shipment_service import (
    get_shipment_by_id,
)
from rag.retrieval import (
    retrieve_operational_knowledge,
)


logger = logging.getLogger(__name__)


# Reported when supporting documents could not be retrieved at all:
# missing Azure configuration, no vector store, or a failed search.
# The cause can name server files and endpoints, so it is only logged.
RETRIEVAL_UNAVAILABLE_LIMITATION = (
    "Supporting document retrieval was unavailable, so this briefing "
    "cites no operational procedures and is based only on the "
    "evidence collected by the investigation."
)

# Reported when the search ran but returned nothing that can be cited.
NO_DOCUMENTS_RETRIEVED_LIMITATION = (
    "No supporting operational documents were retrieved for this "
    "shipment, so this briefing cites no operational procedures and "
    "is based only on the evidence collected by the investigation."
)

# Reported when documents were retrieved but the language model could
# not write the briefing.
DETERMINISTIC_BRIEFING_LIMITATION = (
    "The briefing text was assembled directly from the collected "
    "evidence and retrieved documents because the language model was "
    "unavailable."
)

RETRIEVAL_UNAVAILABLE_SUMMARY = (
    "Supporting operational guidance could not be retrieved, so no "
    "procedures are cited."
)

def format_coverage_days(
    coverage: float,
) -> str:
    """
    Format inventory coverage without unnecessary trailing zeros.
    """
    return format(
        coverage,
        "g",
    )


def build_rag_query(
    shipment_id: str,
    risk_level: RiskLevel,
    delay_probability: float,
    evidence: ToolEvidence,
) -> str:
    """
    Build a grounded retrieval query from evidence collected by
    the Agent Tools.

    Delay probability represents the likelihood of delay. It must not
    be interpreted as a delay duration.
    """
    query_parts = [
        "Supply-chain shipment disruption investigation.",
        f"Shipment reference: {shipment_id}",
        f"Risk level: {risk_level.value}",
        f"Delay probability: {delay_probability:.4f}",
        (
            "Delay probability is not a prediction of the number "
            "of delay days."
        ),
    ]

    if evidence.shipment_summary:
        query_parts.append(
            "Shipment evidence: "
            f"{evidence.shipment_summary}"
        )

    if evidence.historical_delay_summary:
        query_parts.append(
            "Historical delay evidence: "
            f"{evidence.historical_delay_summary}"
        )

    if evidence.weather_summary:
        query_parts.append(
            "Weather evidence: "
            f"{evidence.weather_summary}"
        )

    if evidence.supplier_status:
        query_parts.append(
            "Supplier evidence: "
            f"{evidence.supplier_status}"
        )
    else:
        query_parts.append(
            "Supplier evidence is not currently available."
        )

    if evidence.inventory_summary:
        # The record is product-level: it is matched on product name
        # and says nothing about the stock available to this shipment.
        query_parts.extend(
            [
                (
                    "Inventory evidence (product-level record): "
                    f"{evidence.inventory_summary}"
                ),
                (
                    "Stock availability for this shipment has not "
                    "been verified."
                ),
            ]
        )
    elif (
        evidence.inventory_coverage_days
        is not None
    ):
        coverage_text = format_coverage_days(
            evidence.inventory_coverage_days
        )

        query_parts.append(
            "Inventory coverage: "
            f"{coverage_text} days."
        )
    else:
        query_parts.append(
            "Inventory coverage is not currently available."
        )

    query_parts.extend(
        [
            (
                "Retrieve the most relevant operational "
                "procedures."
            ),
            (
                "Prioritize shipment escalation, inventory "
                "stockout response, replenishment, supplier, "
                "weather, and rerouting guidance supported by "
                "the collected evidence."
            ),
            (
                "Do not assume facts that are not contained "
                "in the collected evidence."
            ),
            (
                "Do not infer delay duration from delay "
                "probability."
            ),
            (
                "Do not treat incoming inventory as guaranteed "
                "or operationally available."
            ),
        ]
    )

    return "\n".join(
        query_parts
    )

def extract_rag_citations(
    retrieved_knowledge: list[dict[str, Any]],
) -> list:
    """
    Extract unique source filenames in retrieval-ranked order.
    """
    citations: list[str] = []
    seen_sources: set[str] = set()

    for result in retrieved_knowledge:
        source = str(
            result.get("source", "")
        ).strip()

        if not source:
            continue

        if source in seen_sources:
            continue

        citations.append(source)
        seen_sources.add(source)

    return citations


def build_guidance_summary(
    retrieved_knowledge: list[dict[str, Any]],
) -> str:
    """
    Build a short deterministic guidance summary using at most one
    excerpt from each retrieved source.
    """
    if not retrieved_knowledge:
        return (
            "No relevant operational guidance was retrieved from "
            "the knowledge base."
        )

    guidance_parts: list[str] = []
    seen_sources: set[str] = set()

    for result in retrieved_knowledge:
        source = str(
            result.get(
                "source",
                "Unknown source",
            )
        ).strip()

        if not source or source in seen_sources:
            continue

        content = " ".join(
            str(
                result.get(
                    "content",
                    "",
                )
            ).split()
        )

        if not content:
            continue

        excerpt = content[:300].rstrip()

        if len(content) > 300:
            excerpt += "..."

        guidance_parts.append(
            f"{source}: {excerpt}"
        )

        seen_sources.add(source)

        if len(guidance_parts) == 3:
            break

    if not guidance_parts:
        return (
            "Operational documents were retrieved, but no usable "
            "guidance text was available."
        )

    return (
        "Retrieved synthetic operational guidance: "
        + " ".join(guidance_parts)
    )


def build_deterministic_actions(
    risk_level: RiskLevel,
    evidence: ToolEvidence,
    retrieved_knowledge: list[dict[str, Any]],
) -> list:
    """
    Build conservative deterministic recommendations.

    This function is used when Azure OpenAI cannot generate a valid
    briefing. Recommendations remain grounded in collected evidence
    and require human operational review.
    """
    actions: list[str] = []

    if risk_level == RiskLevel.HIGH:
        actions.append(
            "Escalate the shipment for immediate human operational "
            "review."
        )
    elif risk_level == RiskLevel.MEDIUM:
        actions.append(
            "Continue the disruption investigation and actively "
            "monitor the shipment."
        )
    else:
        actions.append(
            "Continue routine monitoring because immediate "
            "investigation is not required."
        )

    if evidence.historical_delay_summary:
        actions.append(
            "Consider the elevated historical delay factors during "
            "the operational review."
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

        if (
            severe_weather
            and not low_weather
        ):
            actions.append(
                "Evaluate transport alternatives because the "
                "collected weather evidence indicates potentially "
                "severe conditions."
            )
        elif low_weather:
            actions.append(
                "Continue monitoring destination weather, but do not "
                "reroute solely on the current low-severity weather "
                "evidence."
            )
        else:
            actions.append(
                "Continue monitoring destination weather before "
                "making any rerouting decision."
            )

    if evidence.supplier_status:
        actions.append(
            "Review the alternative supplier candidate when "
            "evaluating sourcing options. Supplier availability, "
            "capacity and commercial terms are not verified and "
            "require human validation before any supplier change."
        )
    else:
        actions.append(
            "Obtain supplier availability and performance evidence "
            "before recommending an alternative supplier."
        )

    if evidence.inventory_summary:
        actions.append(
            "Review the product-level inventory record and confirm "
            "that stock is available for this shipment before relying "
            "on inventory as mitigation."
        )
    elif (
        evidence.inventory_coverage_days
        is not None
    ):
        if (
            evidence.inventory_coverage_days
            <= 3
        ):
            actions.append(
                "Escalate potential stockout exposure because "
                "inventory coverage is three days or less."
            )
        else:
            actions.append(
                "Review available inventory coverage without "
                "assuming a delay duration that was not predicted."
            )
    else:
        actions.append(
            "Obtain current inventory coverage before determining "
            "the shipment's stockout impact."
        )

    if retrieved_knowledge:
        actions.append(
            "Review the retrieved synthetic operational procedures "
            "before approving any mitigation action."
        )

    return actions


def build_deterministic_briefing(
    shipment_id: str,
    risk_level: RiskLevel,
    delay_probability: float,
    evidence: ToolEvidence,
    retrieved_knowledge: list[dict[str, Any]],
    guidance_summary: str | None = None,
) -> LLMBriefingContent:
    """
    Build a grounded briefing without Azure OpenAI.

    This is the safe fallback when Azure is unavailable or returns an
    invalid response, and when no supporting documents were retrieved.
    guidance_summary replaces the summary of retrieved guidance, for
    a briefing that has none to summarize.
    """
    shipment = get_shipment_by_id(
        shipment_id
    )

    destination = ", ".join(
        part
        for part in [
            shipment.destination_city,
            shipment.destination_state,
            shipment.destination_country,
        ]
        if part
    )

    summary_parts = [
        (
            f"Shipment {shipment_id}, containing "
            f"{shipment.quantity} x {shipment.product_name}, has a "
            f"{risk_level.value} predicted delay risk of "
            f"{delay_probability:.1%}."
        ),
        (
            f"The shipment is scheduled for {destination} using "
            f"{shipment.shipping_mode}."
        ),
    ]

    risk_factors: list[str] = []

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
            f"Supplier evidence: {evidence.supplier_status}"
        )

        risk_factors.append(
            evidence.supplier_status
        )
    else:
        summary_parts.append(
            "Supplier availability has not yet been assessed."
        )

    if evidence.inventory_summary:
        summary_parts.append(
            evidence.inventory_summary
        )

        risk_factors.append(
            evidence.inventory_summary
        )
    elif (
        evidence.inventory_coverage_days
        is not None
    ):
        coverage_text = format_coverage_days(
            evidence.inventory_coverage_days
        )

        summary_parts.append(
            "Available inventory coverage is "
            f"{coverage_text} days."
        )
    else:
        summary_parts.append(
            "Inventory coverage has not yet been assessed, so "
            "stockout exposure cannot be confirmed."
        )


    summary_parts.append(
        guidance_summary
        if guidance_summary is not None
        else build_guidance_summary(
            retrieved_knowledge
        )
    )

    return LLMBriefingContent(
        summary=" ".join(summary_parts),
        risk_factors=risk_factors,
        recommended_actions=(
            build_deterministic_actions(
                risk_level=risk_level,
                evidence=evidence,
                retrieved_knowledge=retrieved_knowledge,
            )
        ),
    )


def retrieve_supporting_documents(
    rag_query: str,
    shipment_id: str,
) -> tuple[list[dict[str, Any]], str | None]:
    """
    Retrieve the operational documents that support a briefing.

    Returns the retrieved documents and, when there are none to cite,
    the limitation that explains why. Retrieval is optional: missing
    Azure configuration, a missing vector store or a failed search
    never raises, so the briefing can still be written from the
    evidence the investigation collected.
    """
    try:
        retrieved_knowledge = (
            retrieve_operational_knowledge(
                query=rag_query,
                k=5,
            )
        )
    except Exception:
        logger.warning(
            "Supporting document retrieval was unavailable for "
            "shipment %s. The briefing will cite no documents.",
            shipment_id,
            exc_info=True,
        )

        return [], RETRIEVAL_UNAVAILABLE_LIMITATION

    # A document without a source cannot be cited, so results that
    # yield no citation are treated as no results.
    if (
        not retrieved_knowledge
        or not extract_rag_citations(
            retrieved_knowledge
        )
    ):
        logger.warning(
            "No citable supporting documents were retrieved for "
            "shipment %s. The briefing will cite no documents.",
            shipment_id,
        )

        return [], NO_DOCUMENTS_RETRIEVED_LIMITATION

    return retrieved_knowledge, None


def generate_rag_briefing(
    shipment_id: str,
    risk_level: RiskLevel,
    delay_probability: float,
    evidence: ToolEvidence,
) -> DisruptionBriefingResponse:
    """
    Retrieve operational knowledge and generate a grounded briefing.

    Azure OpenAI is the primary synthesis method. A deterministic,
    evidence-based implementation is retained as a safe fallback.

    Neither retrieval nor Azure OpenAI is required. Without supporting
    documents the briefing is built from the collected evidence alone,
    cites nothing, and says so in its limitations. Citations are only
    ever the sources of documents that were actually retrieved.
    """
    get_shipment_by_id(
        shipment_id
    )

    rag_query = build_rag_query(
        shipment_id=shipment_id,
        risk_level=risk_level,
        delay_probability=delay_probability,
        evidence=evidence,
    )

    retrieved_knowledge, retrieval_limitation = (
        retrieve_supporting_documents(
            rag_query=rag_query,
            shipment_id=shipment_id,
        )
    )

    limitations: list[str] = []

    if retrieval_limitation is not None:
        limitations.append(
            retrieval_limitation
        )

        # Azure OpenAI is given retrieved guidance to ground its
        # answer. Without any, the evidence is reported as collected.
        generated_content = build_deterministic_briefing(
            shipment_id=shipment_id,
            risk_level=risk_level,
            delay_probability=delay_probability,
            evidence=evidence,
            retrieved_knowledge=[],
            guidance_summary=(
                RETRIEVAL_UNAVAILABLE_SUMMARY
                if retrieval_limitation
                == RETRIEVAL_UNAVAILABLE_LIMITATION
                else None
            ),
        )

    else:
        try:
            generated_content = generate_azure_briefing(
                shipment_id=shipment_id,
                risk_level=risk_level,
                delay_probability=delay_probability,
                evidence=evidence,
                retrieved_knowledge=retrieved_knowledge,
            )

            logger.info(
                "Azure OpenAI generated the briefing for shipment %s.",
                shipment_id,
            )

        except AzureOpenAIServiceError as exc:
            logger.warning(
                "Azure OpenAI briefing generation failed for shipment "
                "%s. Using deterministic fallback. Error: %s",
                shipment_id,
                exc,
            )

            limitations.append(
                DETERMINISTIC_BRIEFING_LIMITATION
            )

            generated_content = build_deterministic_briefing(
                shipment_id=shipment_id,
                risk_level=risk_level,
                delay_probability=delay_probability,
                evidence=evidence,
                retrieved_knowledge=retrieved_knowledge,
            )

    return DisruptionBriefingResponse(
        shipment_id=shipment_id,
        risk_level=risk_level,
        delay_probability=delay_probability,
        evidence=evidence,
        # Empty when nothing was retrieved: never a placeholder.
        rag_policy_citations=extract_rag_citations(
            retrieved_knowledge
        ),
        summary=generated_content.summary,
        recommended_actions=(
            generated_content.recommended_actions
        ),
        limitations=limitations,
    )
