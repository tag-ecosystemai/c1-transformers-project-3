"""
Deterministic tools used by the investigation agent.

Each tool wraps an existing backend service. The tools only retrieve
data: risk probabilities come from the prediction service and are never
recalculated here.
"""

from datetime import timedelta
from typing import Any

from backend.models.schemas import (
    InventoryStatusResponse,
    PredictionResponse,
    ShipmentResponse,
)
from backend.services.inventory_service import get_inventory_status
from backend.services.prediction_service import predict_delay_risk
from backend.services.shipment_service import get_shipment_by_id
from backend.services.weather_service import (
    classify_weather_severity,
    describe_weather_code,
    geocode_city,
    get_country_code,
    get_daily_weather,
)


# ============================================================
# SHIPMENT TOOL
# ============================================================


def get_shipment(shipment_id: str) -> ShipmentResponse:
    """
    Retrieve the shipment record for a public shipment reference,
    such as SHP-153440.
    """

    return get_shipment_by_id(shipment_id)


# ============================================================
# RISK TOOL
# ============================================================


def get_delay_risk(shipment_id: str) -> PredictionResponse:
    """
    Return the model's delay probability and risk gate decision.
    """

    return predict_delay_risk(shipment_id)


# ============================================================
# HISTORICAL DELAY CONTEXT TOOL
# ============================================================


def get_historical_delay_context(
    shipment: ShipmentResponse,
) -> dict[str, Any]:
    """
    Report the historical delay rates recorded for the shipment's
    product, market and shipping mode.

    The rates are taken from the shipment record as they are. The
    factor with the highest rate is identified so the briefing can
    point to it; no new rates are estimated.
    """

    delay_rates = {
        "product": shipment.historical_product_delay_rate,
        "market": shipment.historical_market_delay_rate,
        "shipping_mode": shipment.historical_shipping_mode_delay_rate,
    }

    highest_factor = max(
        delay_rates,
        key=delay_rates.get,
    )

    return {
        "product_name": shipment.product_name,
        "market": shipment.market,
        "shipping_mode": shipment.shipping_mode,
        "scheduled_shipping_days": shipment.scheduled_shipping_days,
        "historical_delay_rates": delay_rates,
        "highest_delay_rate_factor": highest_factor,
    }


# ============================================================
# WEATHER TOOL
# ============================================================


WEATHER_WINDOW_BASIS = (
    "Approximate window: order date to order date plus scheduled "
    "shipping days, observed at the geocoded destination city. "
    "This is not route-level weather."
)


def get_destination_weather(
    shipment: ShipmentResponse,
) -> dict[str, Any]:
    """
    Report the historical weather observed at the shipment's
    destination city during its scheduled transit window.

    The dataset has no actual dispatch date, so the window starts at
    the order date. The shipment's latitude and longitude are not used
    because they do not describe the destination.

    Raises WeatherServiceError when the weather cannot be retrieved.
    """

    country_code = get_country_code(shipment.destination_country)
    location = geocode_city(shipment.destination_city, country_code)

    window_start = shipment.order_date.date()
    window_end = window_start + timedelta(
        days=shipment.scheduled_shipping_days
    )

    daily = get_daily_weather(
        location["latitude"],
        location["longitude"],
        window_start,
        window_end,
    )

    precipitation = [day["precipitation_mm"] for day in daily]
    # Higher WMO codes describe more significant weather, so the
    # highest code in the window is its worst condition.
    worst_code = max(day["weather_code"] for day in daily)

    return {
        "destination": f"{location['name']}, {location['country']}",
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "window_basis": WEATHER_WINDOW_BASIS,
        "daily": [dict(day) for day in daily],
        "precipitation_total_mm": round(sum(precipitation), 1),
        "precipitation_max_mm": max(precipitation),
        "max_wind_speed_kmh": max(
            day["max_wind_speed_kmh"] for day in daily
        ),
        "worst_weather_code": worst_code,
        "worst_weather_description": describe_weather_code(worst_code),
        "severity": classify_weather_severity(worst_code),
        "source": "Open-Meteo historical archive",
    }


# ============================================================
# INVENTORY TOOL
# ============================================================


def get_inventory_coverage(
    shipment: ShipmentResponse,
) -> InventoryStatusResponse:
    """
    Report the synthetic inventory record held for the shipment's
    product, matched on the exact product name.

    The record describes the product, not the shipment: it does not
    show that stock is available to fulfil this shipment, and its
    warehouse and supplier are unrelated to the shipment.

    Raises InventoryServiceError when the inventory cannot be read or
    matched, and its subclass InventoryNotFoundError when the product
    has no inventory record.
    """

    return get_inventory_status(shipment.product_name)
