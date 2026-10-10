from fastapi.testclient import (
    TestClient,
)

from backend.api import (
    routes_predictions,
)
from backend.main import app
from backend.services.shipment_service import (
    ShipmentDataUnavailableError,
)


client = TestClient(
    app
)


def test_application_starts_and_reports_health():
    response = client.get(
        "/health"
    )

    assert response.status_code == 200

    assert (
        response.json()["status"]
        == "healthy"
    )


def test_application_registers_required_routes():
    paths = client.get(
        "/openapi.json"
    ).json()["paths"]

    assert (
        "/api/shipments/"
        "{shipment_reference}"
        in paths
    )

    assert (
        "/api/predictions/evaluate/"
        "{shipment_id}"
        in paths
    )

    assert (
        "/api/agent/investigate/"
        "{shipment_id}"
        in paths
    )

    assert (
        "/api/agent/investigate/"
        "{shipment_id}/stream"
        in paths
    )

    assert (
        "/api/inventory/shipment/"
        "{shipment_reference}"
        in paths
    )


def test_inventory_route_uses_get_method():
    paths = client.get(
        "/openapi.json"
    ).json()["paths"]

    inventory_route = paths[
        "/api/inventory/shipment/"
        "{shipment_reference}"
    ]

    assert (
        "get"
        in inventory_route
    )


def test_prediction_returns_503_when_shipment_data_unavailable(
    monkeypatch,
):
    def unavailable(
        shipment_id,
    ):
        raise ShipmentDataUnavailableError(
            "dataset missing"
        )

    monkeypatch.setattr(
        routes_predictions,
        "predict_delay_risk",
        unavailable,
    )

    response = client.post(
        "/api/predictions/evaluate/"
        "SHP-153440"
    )

    assert response.status_code == 503

    assert response.json()[
        "detail"
    ] == "dataset missing"