import pandas as pd
import pytest

from backend.models.schemas import (
    InventoryStatusResponse,
    PredictionResponse,
    RiskLevel,
)
from backend.services import (
    agent_service,
    agent_tools,
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
    """

    def network_blocked(*args, **kwargs):
        raise AssertionError("Tests must not call the live weather API.")

    monkeypatch.setattr(weather_service.requests, "get", network_blocked)
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
