from types import SimpleNamespace

import pandas as pd
import pytest
import requests

from backend.models.schemas import (
    InventoryStatusResponse,
    LLMBriefingContent,
    PredictionResponse,
    RiskLevel,
    SupplierCandidate,
    SupplierRecommendation,
)
from backend.services import (
    agent_service,
    agent_tools,
    briefing_service,
    inventory_service,
    shipment_service,
    weather_service,
)


WEATHER_EVIDENCE = {
    "destination": "Vassouras, Brazil",
    "latitude": -22.4036,
    "longitude": -43.6625,
    "window_start": "2017-05-01",
    "window_end": "2017-05-05",
    "window_basis": agent_tools.WEATHER_WINDOW_BASIS,
    "daily": [],
    "precipitation_total_mm": 9.2,
    "precipitation_max_mm": 8.9,
    "max_wind_speed_kmh": 17.9,
    "worst_weather_code": 61,
    "worst_weather_description": "slight rain",
    "severity": "low",
    "source": "Open-Meteo historical archive",
}


@pytest.fixture(autouse=True)
def no_live_weather(monkeypatch):
    """
    Keep every test offline and independent.

    HTTP calls fail unless a test mocks them, cached weather lookups are
    cleared, and the agent receives fixed weather evidence unless a test
    replaces it.

    Only the requests reference inside weather_service is replaced. The
    shared requests package stays available to RAG, Azure OpenAI and
    other integrations.
    """

    def network_blocked(*args, **kwargs):
        raise AssertionError("Tests must not call the live weather API.")

    weather_requests = SimpleNamespace(
        get=network_blocked,
        exceptions=requests.exceptions,
        Timeout=requests.Timeout,
        ConnectionError=requests.ConnectionError,
        HTTPError=requests.HTTPError,
        RequestException=requests.RequestException,
    )
    monkeypatch.setattr(weather_service, "requests", weather_requests)
    monkeypatch.setattr(
        agent_service,
        "get_destination_weather",
        lambda shipment: WEATHER_EVIDENCE,
    )

    weather_service.geocode_city.cache_clear()
    weather_service.get_daily_weather.cache_clear()
    yield
    weather_service.geocode_city.cache_clear()
    weather_service.get_daily_weather.cache_clear()


# The warehouse, supplier, reorder point and replenishment date are
# distinctive so a test can show that none of them is reported.
INVENTORY_RECORD = InventoryStatusResponse(
    inventory_id="INV-TEST-01",
    product_id="PROD-TEST-01",
    product_name="Trail Running Shoe",
    category="Cleats",
    department="Footwear",
    warehouse_id="WH-TEST-07",
    warehouse_location="Rotterdam",
    warehouse_country="Netherlands",
    supplier_id="SUP-TEST-99",
    current_stock=420,
    reserved_stock=26,
    available_stock=394,
    daily_demand=23,
    safety_stock=120,
    reorder_point=4321,
    incoming_quantity=150,
    expected_replenishment_date="2017-06-21",
    inventory_coverage_days=17.13,
    stockout_risk=RiskLevel.LOW,
    below_safety_stock=False,
    below_reorder_point=True,
    matched_on=inventory_service.MATCHED_ON,
    data_source=inventory_service.SYNTHETIC_DATA_SOURCE,
    limitations=list(inventory_service.STANDING_LIMITATIONS),
)


@pytest.fixture(autouse=True)
def fixed_inventory(monkeypatch):
    """
    Give the agent a fixed inventory record unless a test replaces it,
    so investigations do not depend on the inventory dataset.
    """
    monkeypatch.setattr(
        agent_service,
        "get_inventory_coverage",
        lambda shipment: INVENTORY_RECORD,
    )


SUPPLIER_CANDIDATE = SupplierCandidate(
    supplier_id="SUP-TEST-03",
    supplier_name="NorthStar Logistics",
    supplier_country="Bután",
    product_category="Sporting Goods",
    average_lead_time_days=8.5,
    on_time_delivery_rate=0.877,
    cancellation_rate=0.088,
    quality_issue_rate=0.066,
    capacity_utilization=0.584,
    supplier_risk_score=19.68,
    supplier_risk_level=RiskLevel.MEDIUM,
    data_source="SYNTHETIC_MVP",
)

HIGH_RISK_SUPPLIER_CANDIDATE = SUPPLIER_CANDIDATE.model_copy(
    update={
        "supplier_id": "SUP-TEST-16",
        "supplier_name": "DirectSource Global",
        "supplier_country": "Noruega",
        "product_category": "Men's Footwear",
        "average_lead_time_days": 2.3,
        "supplier_risk_score": 25.7,
        "supplier_risk_level": RiskLevel.HIGH,
    }
)

# The service's own note, which the investigation does not pass on.
SUPPLIER_SERVICE_NOTE = (
    "Supplier records are synthetic demonstration data. No selected "
    "candidate country matches the shipment destination, so geographic "
    "suitability requires additional review."
)

SUPPLIER_RECOMMENDATION = SupplierRecommendation(
    category="Cleats",
    destination_country="Brasil",
    required_quantity=2,
    recommended_supplier=SUPPLIER_CANDIDATE,
    alternatives=[SUPPLIER_CANDIDATE, HIGH_RISK_SUPPLIER_CANDIDATE],
    candidate_count=2,
    data_source="SYNTHETIC_MVP",
    quantity_capacity_verified=False,
    limitation=SUPPLIER_SERVICE_NOTE,
)


@pytest.fixture(autouse=True)
def fixed_supplier(monkeypatch):
    """
    Give the agent a fixed supplier recommendation unless a test
    replaces it, so investigations do not depend on the supplier
    dataset.
    """
    monkeypatch.setattr(
        agent_service,
        "get_alternative_suppliers",
        lambda shipment: SUPPLIER_RECOMMENDATION,
    )


SHIPMENT_RECORD = {
    "order_id": 61458,
    "shipment_id": 153440,
    "shipment_reference": "SHP-153440",
    "product_name": "Trail Running Shoe",
    "category": "Cleats",
    "department": "Footwear",
    "market": "LATAM",
    "customer_country": "EE. UU.",
    "destination_country": "Brasil",
    "destination_region": "South America",
    "destination_state": "Rio de Janeiro",
    "destination_city": "Vassouras",
    "shipping_mode": "Standard Class",
    "scheduled_shipping_days": 4,
    "quantity": 2,
    "product_price": 59.99,
    "sales": 119.98,
    "discount": 6.0,
    "order_date": "2017-05-01 10:30:00",
    "latitude": 39.8166,
    "longitude": -74.9847,
    "historical_product_delay_rate": 0.57,
    "historical_market_delay_rate": 0.55,
    "historical_shipping_mode_delay_rate": 0.38,
}


@pytest.fixture(autouse=True)
def mock_azure_briefing(
    monkeypatch,
):
    """
    Replace RAG retrieval and Azure OpenAI synthesis with deterministic
    offline content.

    Every test uses this fixture, so no test consumes Azure tokens or
    depends on network availability or the vector store. A test that
    exercises retrieval or synthesis replaces these mocks itself. Real
    RAG and Azure behavior are tested separately by integration tests.
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
                "Elevated-risk shipments require investigation "
                "and human operational review."
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
                "Low-severity weather does not independently "
                "justify immediate rerouting."
            ),
            "metadata": {
                "data_source": "SYNTHETIC_MVP",
            },
        },
        {
            "rank": 3,
            "source": (
                "03_supplier_alternative_policy.pdf"
            ),
            "source_path": (
                "03_supplier_alternative_policy.pdf"
            ),
            "relevance_score": 0.80,
            "content": (
                "Synthetic alternative suppliers require geographic, "
                "capacity, commercial, and contractual validation."
            ),
            "metadata": {
                "data_source": "SYNTHETIC_MVP",
            },
        },
    ]

    monkeypatch.setattr(
        briefing_service,
        "retrieve_operational_knowledge",
        lambda query, k=5: (
            retrieved_documents[:k]
        ),
    )

    def deterministic_azure_briefing(
        shipment_id,
        risk_level,
        delay_probability,
        evidence,
        retrieved_knowledge,
    ):
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
            coverage_text = format(
                evidence.inventory_coverage_days,
                "g",
            )

            summary_parts.append(
                "Available inventory coverage is "
                f"{coverage_text} days."
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

            if (
                severe_weather
                and not low_weather
            ):
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
                "Validate the supplier candidate geographically, "
                "commercially, and operationally before considering "
                "a supplier change."
            )
        else:
            recommended_actions.append(
                "Obtain supplier availability and performance "
                "evidence before recommending an alternative."
            )

        if evidence.inventory_summary:
            recommended_actions.append(
                "Review the product-level inventory record and check "
                "stock for this shipment before relying on inventory "
                "as mitigation."
            )
        elif (
            evidence.inventory_coverage_days
            is None
        ):
            recommended_actions.append(
                "Obtain inventory coverage before determining "
                "stockout exposure."
            )
        elif (
            evidence.inventory_coverage_days
            <= 3
        ):
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
            summary=" ".join(
                summary_parts
            ),
            risk_factors=risk_factors,
            recommended_actions=(
                recommended_actions
            ),
        )

    monkeypatch.setattr(
        briefing_service,
        "generate_azure_briefing",
        deterministic_azure_briefing,
    )


@pytest.fixture
def shipment_data(monkeypatch):
    """
    Replace the Shipment Tool dataset with one known record.
    """
    dataframe = pd.DataFrame([SHIPMENT_RECORD])
    monkeypatch.setattr(
        shipment_service,
        "load_shipment_data",
        lambda: dataframe,
    )
    return dataframe


@pytest.fixture
def shipment(shipment_data):
    return shipment_service.get_shipment_by_id("SHP-153440")


def make_prediction(
    risk_level: RiskLevel,
    probability: float,
    requires_investigation: bool,
) -> PredictionResponse:
    return PredictionResponse(
        shipment_id="SHP-153440",
        delay_probability=probability,
        risk_level=risk_level,
        requires_investigation=requires_investigation,
    )


@pytest.fixture
def high_risk(monkeypatch, shipment_data):
    """
    Mock the model so the shipment passes the risk gate.
    """
    prediction = make_prediction(RiskLevel.HIGH, 0.82, True)
    monkeypatch.setattr(
        agent_tools,
        "predict_delay_risk",
        lambda shipment_id: prediction,
    )
    return prediction


@pytest.fixture
def low_risk(monkeypatch, shipment_data):
    """
    Mock the model so the shipment is stopped by the risk gate.
    """
    prediction = make_prediction(RiskLevel.LOW, 0.12, False)
    monkeypatch.setattr(
        agent_tools,
        "predict_delay_risk",
        lambda shipment_id: prediction,
    )
    return prediction
