from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import (
    TestClient,
)

from backend.api import (
    routes_inventory,
)
from backend.api.routes_inventory import (
    INVENTORY_NOT_FOUND_DETAIL,
    INVENTORY_UNAVAILABLE_DETAIL,
    ProductInventoryRecord,
)
from backend.config import settings
from backend.exceptions import (
    InventoryNotFoundError,
    InventoryServiceError,
)
from backend.models.schemas import (
    InventoryStatusResponse,
    RiskLevel,
)
from backend.services import inventory_service
from backend.services.agent_service import (
    INVENTORY_SCOPE_LIMITATION,
    INVENTORY_TRACE_FIELDS,
)
from backend.services.shipment_service import (
    InvalidShipmentReferenceError,
    ShipmentDataUnavailableError,
    ShipmentDataValidationError,
    ShipmentNotFoundError,
)


INVENTORY_URL = (
    "/api/inventory/shipment/"
    "SHP-153440"
)


@pytest.fixture
def client():
    app = FastAPI()

    app.include_router(
        routes_inventory.router
    )

    return TestClient(
        app
    )


def make_inventory_status():
    """
    Create a deterministic product-level inventory record for API
    tests. The warehouse, supplier, identifiers, reorder point and
    replenishment date are distinctive so a test can show that none
    of them is returned.
    """
    return InventoryStatusResponse(
        inventory_id="INV-TEST",
        product_id="PROD-TEST",
        product_name="Trail Running Shoe",
        category="Cleats",
        department="Footwear",
        warehouse_id="WH-TEST",
        warehouse_location="Sao Paulo",
        warehouse_country="Brazil",
        supplier_id="SUP-TEST",
        current_stock=400,
        reserved_stock=100,
        available_stock=300,
        daily_demand=50,
        safety_stock=200,
        reorder_point=451,
        incoming_quantity=200,
        expected_replenishment_date=date(
            2017,
            5,
            8,
        ),
        inventory_coverage_days=6.25,
        stockout_risk=RiskLevel.MEDIUM,
        below_safety_stock=False,
        below_reorder_point=True,
        matched_on=inventory_service.MATCHED_ON,
        data_source="SYNTHETIC_MVP",
        limitations=list(
            inventory_service.STANDING_LIMITATIONS
        ),
    )


def use_shipment(
    monkeypatch,
    shipment,
):
    monkeypatch.setattr(
        routes_inventory,
        "get_shipment_by_id",
        lambda reference: shipment,
    )


def fail_inventory(
    monkeypatch,
    error,
):
    def inventory_failure(
        product_name,
    ):
        raise error

    monkeypatch.setattr(
        routes_inventory,
        "get_inventory_status",
        inventory_failure,
    )


def test_inventory_endpoint_returns_structured_evidence(
    client,
    shipment,
    monkeypatch,
):
    expected = (
        make_inventory_status()
    )

    calls = []

    use_shipment(
        monkeypatch,
        shipment,
    )

    # The service is given the product name and nothing else: the
    # shipment's destination plays no part in the lookup.
    def fake_inventory_status(
        product_name,
    ):
        calls.append(
            product_name
        )

        return expected

    monkeypatch.setattr(
        routes_inventory,
        "get_inventory_status",
        fake_inventory_status,
    )

    response = client.get(
        INVENTORY_URL
    )

    assert response.status_code == 200

    body = response.json()

    ProductInventoryRecord.model_validate(
        body
    )

    assert body == {
        "product_name": "Trail Running Shoe",
        "current_stock": 400,
        "reserved_stock": 100,
        "available_stock": 300,
        "daily_demand": 50,
        "safety_stock": 200,
        "incoming_quantity": 200,
        "inventory_coverage_days": 6.25,
        "stockout_risk": "MEDIUM",
        "below_safety_stock": False,
        "matched_on": (
            "product_name (exact, ignoring case and accents)"
        ),
        "data_source": "SYNTHETIC_MVP",
        "limitation": INVENTORY_SCOPE_LIMITATION,
    }

    assert calls == [
        "Trail Running Shoe",
    ]


def test_inventory_endpoint_returns_only_the_reviewed_fields(
    client,
    shipment,
    monkeypatch,
):
    use_shipment(
        monkeypatch,
        shipment,
    )

    monkeypatch.setattr(
        routes_inventory,
        "get_inventory_status",
        lambda product_name: (
            make_inventory_status()
        ),
    )

    response = client.get(
        INVENTORY_URL
    )

    # The same fields the investigation records in its tool trace.
    assert set(response.json()) == {
        *INVENTORY_TRACE_FIELDS,
        "limitation",
    }

    for detail in (
        "warehouse",
        "WH-TEST",
        "Sao Paulo",
        "Brazil",
        "supplier",
        "SUP-TEST",
        "inventory_id",
        "INV-TEST",
        "product_id",
        "PROD-TEST",
        "reorder",
        "451",
        "replenishment",
        "2017-05-08",
        "destination_country",
        "calculation_verified",
    ):
        assert detail not in response.text, detail


def test_inventory_endpoint_states_the_record_is_product_level(
    client,
    shipment,
    monkeypatch,
):
    use_shipment(
        monkeypatch,
        shipment,
    )

    monkeypatch.setattr(
        routes_inventory,
        "get_inventory_status",
        lambda product_name: (
            make_inventory_status()
        ),
    )

    body = client.get(
        INVENTORY_URL
    ).json()

    assert body["limitation"] == (
        "Inventory record available; stock availability for this "
        "shipment has not been verified."
    )

    assert body["matched_on"].startswith(
        "product_name"
    )

    operation = client.get(
        "/openapi.json"
    ).json()["paths"][
        "/api/inventory/shipment/{shipment_reference}"
    ]["get"]

    assert (
        "product-level"
        in operation["summary"]
    )

    assert (
        "does not verify that stock is available for the shipment"
        in operation["description"]
    )


def test_inventory_endpoint_returns_400_for_invalid_reference(
    client,
    monkeypatch,
):
    def invalid_reference(
        reference,
    ):
        raise InvalidShipmentReferenceError(
            "Invalid shipment reference."
        )

    monkeypatch.setattr(
        routes_inventory,
        "get_shipment_by_id",
        invalid_reference,
    )

    response = client.get(
        "/api/inventory/shipment/"
        "not-a-shipment"
    )

    assert response.status_code == 400

    assert response.json() == {
        "detail": (
            "Invalid shipment reference."
        ),
    }


def test_inventory_endpoint_returns_404_for_unknown_shipment(
    client,
    monkeypatch,
):
    def shipment_not_found(
        reference,
    ):
        raise ShipmentNotFoundError(
            f"Shipment '{reference}' "
            "was not found."
        )

    monkeypatch.setattr(
        routes_inventory,
        "get_shipment_by_id",
        shipment_not_found,
    )

    response = client.get(
        "/api/inventory/shipment/"
        "SHP-999999"
    )

    assert response.status_code == 404

    assert (
        "was not found"
        in response.json()["detail"]
    )


def test_inventory_endpoint_returns_404_when_inventory_is_missing(
    client,
    shipment,
    monkeypatch,
):
    use_shipment(
        monkeypatch,
        shipment,
    )

    fail_inventory(
        monkeypatch,
        InventoryNotFoundError(
            "No synthetic inventory record was found for product "
            "'Trail Running Shoe'."
        ),
    )

    response = client.get(
        INVENTORY_URL
    )

    assert response.status_code == 404

    # A fixed message: the service's own wording is not returned.
    assert response.json() == {
        "detail": (
            "No inventory record is held for this shipment's "
            "product."
        ),
    }

    assert (
        response.json()["detail"]
        == INVENTORY_NOT_FOUND_DETAIL
    )

    assert (
        "synthetic"
        not in response.text.lower()
    )


def test_inventory_endpoint_returns_422_for_invalid_shipment_record(
    client,
    monkeypatch,
):
    def invalid_shipment_data(
        reference,
    ):
        raise ShipmentDataValidationError(
            "Shipment record is invalid."
        )

    monkeypatch.setattr(
        routes_inventory,
        "get_shipment_by_id",
        invalid_shipment_data,
    )

    response = client.get(
        INVENTORY_URL
    )

    assert response.status_code == 422

    assert response.json() == {
        "detail": (
            "Shipment record is invalid."
        ),
    }


def test_inventory_endpoint_returns_503_when_shipment_data_is_unavailable(
    client,
    monkeypatch,
):
    def unavailable_shipment_data(
        reference,
    ):
        raise ShipmentDataUnavailableError(
            "Shipment dataset unavailable."
        )

    monkeypatch.setattr(
        routes_inventory,
        "get_shipment_by_id",
        unavailable_shipment_data,
    )

    response = client.get(
        INVENTORY_URL
    )

    assert response.status_code == 503

    assert response.json() == {
        "detail": (
            "Shipment dataset unavailable."
        ),
    }


def test_inventory_endpoint_returns_503_when_inventory_service_fails(
    client,
    shipment,
    monkeypatch,
):
    use_shipment(
        monkeypatch,
        shipment,
    )

    fail_inventory(
        monkeypatch,
        InventoryServiceError(
            "The inventory dataset has 3 record(s) where "
            "'available_stock' is negative."
        ),
    )

    response = client.get(
        INVENTORY_URL
    )

    assert response.status_code == 503

    # A fixed message: the service's own wording is not returned.
    assert response.json() == {
        "detail": (
            "Inventory data is currently unavailable."
        ),
    }

    assert (
        response.json()["detail"]
        == INVENTORY_UNAVAILABLE_DETAIL
    )


def test_inventory_service_error_does_not_expose_a_file_path(
    client,
    shipment,
    monkeypatch,
):
    use_shipment(
        monkeypatch,
        shipment,
    )

    fail_inventory(
        monkeypatch,
        InventoryServiceError(
            "Inventory data was not found at: "
            "C:\\srv\\app\\data\\processed\\inventory_tool_data.csv"
        ),
    )

    response = client.get(
        INVENTORY_URL
    )

    assert response.status_code == 503

    assert response.json() == {
        "detail": INVENTORY_UNAVAILABLE_DETAIL,
    }

    for detail in (
        "C:",
        "srv",
        "processed",
        "inventory_tool_data.csv",
        "was not found at",
    ):
        assert detail not in response.text, detail


def test_missing_inventory_dataset_does_not_expose_its_path(
    client,
    shipment,
    monkeypatch,
    tmp_path,
):
    """
    The real service, pointed at a dataset that does not exist.
    """
    use_shipment(
        monkeypatch,
        shipment,
    )

    monkeypatch.setattr(
        settings,
        "inventory_data_path",
        tmp_path / "private" / "inventory_tool_data.csv",
    )

    inventory_service.clear_inventory_cache()

    try:
        response = client.get(
            INVENTORY_URL
        )
    finally:
        inventory_service.clear_inventory_cache()

    assert response.status_code == 503

    assert response.json() == {
        "detail": INVENTORY_UNAVAILABLE_DETAIL,
    }

    assert "private" not in response.text
    assert tmp_path.name not in response.text


def test_inventory_endpoint_reads_the_record_by_product_name(
    client,
    shipment,
    monkeypatch,
    tmp_path,
):
    """
    The real service, with a dataset that holds the shipment's product.
    """
    use_shipment(
        monkeypatch,
        shipment.model_copy(
            update={
                "product_name": (
                    "Perfect Fitness Perfect Rip Deck"
                ),
            }
        ),
    )

    inventory_service.clear_inventory_cache()

    try:
        response = client.get(
            INVENTORY_URL
        )
    finally:
        inventory_service.clear_inventory_cache()

    assert response.status_code == 200

    body = response.json()

    assert (
        body["product_name"]
        == "Perfect Fitness Perfect Rip Deck"
    )

    # Fractional coverage is returned as recorded, not rounded.
    assert (
        body["inventory_coverage_days"]
        == 3.93
    )

    assert (
        body["limitation"]
        == INVENTORY_SCOPE_LIMITATION
    )
