from datetime import date

import pytest

from backend.exceptions import WeatherServiceError
from backend.models.schemas import ShipmentResponse
from backend.services import agent_tools
from backend.services.agent_tools import (
    WEATHER_WINDOW_BASIS,
    get_alternative_suppliers,
    get_delay_risk,
    get_destination_weather,
    get_historical_delay_context,
    get_inventory_coverage,
    get_shipment,
)
from backend.services.shipment_service import (
    InvalidShipmentReferenceError,
    ShipmentNotFoundError,
)


def test_get_shipment_returns_shipment_record(shipment_data):
    shipment = get_shipment("shp-153440")

    assert isinstance(shipment, ShipmentResponse)
    assert shipment.shipment_reference == "SHP-153440"
    assert shipment.category == "Cleats"
    assert shipment.destination_city == "Vassouras"


def test_get_shipment_unknown_reference_raises(shipment_data):
    with pytest.raises(ShipmentNotFoundError):
        get_shipment("SHP-999999")


def test_get_shipment_invalid_reference_raises(shipment_data):
    with pytest.raises(InvalidShipmentReferenceError):
        get_shipment("ABC-1")


def test_get_delay_risk_returns_prediction_service_result(monkeypatch):
    calls = []
    sentinel = object()

    def fake_predict(shipment_id):
        calls.append(shipment_id)
        return sentinel

    monkeypatch.setattr(agent_tools, "predict_delay_risk", fake_predict)

    assert get_delay_risk("SHP-153440") is sentinel
    assert calls == ["SHP-153440"]


def test_get_historical_delay_context_reports_recorded_rates(shipment):
    context = get_historical_delay_context(shipment)

    assert context == {
        "product_name": "Trail Running Shoe",
        "market": "LATAM",
        "shipping_mode": "Standard Class",
        "scheduled_shipping_days": 4,
        "historical_delay_rates": {
            "product": 0.57,
            "market": 0.55,
            "shipping_mode": 0.38,
        },
        "highest_delay_rate_factor": "product",
        "highest_delay_rate": 0.57,
        "source": "shipment_tool_data.csv",
    }


def test_get_historical_delay_context_identifies_highest_factor(shipment):
    shipment = shipment.model_copy(
        update={"historical_shipping_mode_delay_rate": 0.9}
    )

    context = get_historical_delay_context(shipment)

    assert context["highest_delay_rate_factor"] == "shipping_mode"


def test_get_destination_weather_summarizes_transit_window(
    shipment,
    monkeypatch,
):
    requests_made = {}

    def fake_geocode(city, country_code):
        requests_made["geocode"] = (city, country_code)
        return {
            "name": "Vassouras",
            "country": "Brazil",
            "latitude": -22.4036,
            "longitude": -43.6625,
        }

    def fake_daily_weather(latitude, longitude, start_date, end_date):
        requests_made["weather"] = (latitude, longitude, start_date, end_date)
        return (
            {"date": "2017-05-01", "precipitation_mm": 8.9,
             "max_wind_speed_kmh": 17.9, "weather_code": 61},
            {"date": "2017-05-02", "precipitation_mm": 0.3,
             "max_wind_speed_kmh": 22.1, "weather_code": 95},
            {"date": "2017-05-03", "precipitation_mm": 0.0,
             "max_wind_speed_kmh": 12.8, "weather_code": 3},
        )

    monkeypatch.setattr(agent_tools, "geocode_city", fake_geocode)
    monkeypatch.setattr(agent_tools, "get_daily_weather", fake_daily_weather)

    weather = get_destination_weather(shipment)

    # Destination city and country, not the shipment's own coordinates.
    assert requests_made["geocode"] == ("Vassouras", "BR")
    # Order date 2017-05-01 plus 4 scheduled shipping days.
    assert requests_made["weather"] == (
        -22.4036, -43.6625, date(2017, 5, 1), date(2017, 5, 5)
    )
    assert {key: value for key, value in weather.items() if key != "daily"} == {
        "destination": "Vassouras, Brazil",
        "latitude": -22.4036,
        "longitude": -43.6625,
        "window_start": "2017-05-01",
        "window_end": "2017-05-05",
        "window_basis": WEATHER_WINDOW_BASIS,
        "precipitation_total_mm": 9.2,
        "precipitation_max_mm": 8.9,
        "max_wind_speed_kmh": 22.1,
        "worst_weather_code": 95,
        "worst_weather_description": "thunderstorm",
        "severity": "high",
        "source": "Open-Meteo historical archive",
    }
    assert len(weather["daily"]) == 3
    assert "not route-level weather" in weather["window_basis"]


def test_get_destination_weather_rejects_unmapped_country(shipment):
    shipment = shipment.model_copy(update={"destination_country": "Atlantis"})

    with pytest.raises(WeatherServiceError, match="Atlantis"):
        get_destination_weather(shipment)


def test_get_alternative_suppliers_returns_synthetic_candidates(
    shipment,
):
    result = (
        get_alternative_suppliers(
            shipment=shipment,
            limit=3,
        )
    )

    assert result.alternatives

    assert (
        result.data_source
        == "SYNTHETIC_MVP"
    )

    assert (
        result.quantity_capacity_verified
        is False
    )

    for supplier in result.alternatives:
        assert (
            supplier.data_source
            == "SYNTHETIC_MVP"
        )


def test_get_inventory_coverage_looks_up_the_shipment_product(
    shipment,
    monkeypatch,
):
    calls = []
    sentinel = object()

    def fake_inventory_status(product_name):
        calls.append(product_name)
        return sentinel

    monkeypatch.setattr(
        agent_tools,
        "get_inventory_status",
        fake_inventory_status,
    )

    assert get_inventory_coverage(shipment) is sentinel
    assert calls == ["Trail Running Shoe"]
