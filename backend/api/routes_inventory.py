import logging

from fastapi import (
    APIRouter,
    HTTPException,
    status,
)
from pydantic import (
    BaseModel,
    Field,
)

from backend.exceptions import (
    InventoryNotFoundError,
    InventoryServiceError,
)
from backend.models.schemas import (
    InventoryStatusResponse,
    RiskLevel,
)
from backend.services.agent_service import (
    INVENTORY_SCOPE_LIMITATION,
    INVENTORY_TRACE_FIELDS,
)
from backend.services.inventory_service import (
    get_inventory_status,
)
from backend.services.shipment_service import (
    InvalidShipmentReferenceError,
    ShipmentDataUnavailableError,
    ShipmentDataValidationError,
    ShipmentNotFoundError,
    get_shipment_by_id,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/inventory",
    tags=["Inventory"],
)


# Returned in place of an inventory failure's own message, which can
# name server files and is only written to the log.
INVENTORY_NOT_FOUND_DETAIL = (
    "No inventory record is held for this shipment's product."
)

INVENTORY_UNAVAILABLE_DETAIL = (
    "Inventory data is currently unavailable."
)


class ProductInventoryRecord(BaseModel):
    """
    The inventory record held for the product on a shipment.

    The record is product-level evidence: it is matched on product
    name only and does not show that stock is available for the
    shipment. It carries the same reviewed fields the investigation
    records in its tool trace. The warehouse, supplier, internal
    identifiers, reorder point and replenishment date of a record are
    not returned because none of them can be related to the shipment.
    """

    product_name: str = Field(
        ...,
        description="Product the inventory record describes",
    )

    current_stock: int = Field(
        ...,
        ge=0,
        description="Units in stock",
    )

    reserved_stock: int = Field(
        ...,
        ge=0,
        description="Units in stock that are already reserved",
    )

    available_stock: int = Field(
        ...,
        ge=0,
        description="Current stock minus reserved stock",
    )

    daily_demand: int = Field(
        ...,
        gt=0,
        description="Average units demanded per day",
    )

    safety_stock: int = Field(
        ...,
        ge=0,
        description="Safety-stock threshold in units",
    )

    incoming_quantity: int = Field(
        ...,
        ge=0,
        description="Units recorded as incoming",
    )

    inventory_coverage_days: float = Field(
        ...,
        ge=0,
        description=(
            "Available stock divided by daily demand, as recorded "
            "(fractional days)"
        ),
    )

    stockout_risk: RiskLevel = Field(
        ...,
        description="Stockout-risk classification as recorded",
    )

    below_safety_stock: bool = Field(
        ...,
        description="Whether available stock is at or below safety stock",
    )

    matched_on: str = Field(
        ...,
        description="How the record was matched to the shipment's product",
    )

    data_source: str = Field(
        ...,
        description="Source label of the inventory record",
    )

    limitation: str = Field(
        ...,
        description="What this inventory record does not establish",
    )


def _to_product_inventory_record(
    record: InventoryStatusResponse,
) -> ProductInventoryRecord:
    return ProductInventoryRecord(
        **record.model_dump(
            include=INVENTORY_TRACE_FIELDS,
        ),
        limitation=INVENTORY_SCOPE_LIMITATION,
    )


@router.get(
    "/shipment/{shipment_reference}",
    response_model=ProductInventoryRecord,
    summary=(
        "Retrieve the product-level inventory record for a "
        "shipment's product"
    ),
    description=(
        "Retrieve the inventory record held for the product on a "
        "shipment, identified by a public shipment reference such "
        "as SHP-153440. The record is matched on product name only. "
        "It is product-level evidence and does not verify that stock "
        "is available for the shipment."
    ),
)
def fetch_shipment_inventory(
    shipment_reference: str,
) -> ProductInventoryRecord:
    """
    Retrieve the inventory record for a shipment's product.

    The endpoint first retrieves the leakage-safe shipment record,
    then looks up the inventory record with the same product name.
    Nothing about the shipment other than its product name is used,
    so the result says nothing about stock at the destination.

    Possible responses:

    - 200: Inventory record successfully retrieved
    - 400: Invalid shipment-reference format
    - 404: Shipment or matching inventory record does not exist
    - 422: Shipment record violates the API contract
    - 503: Shipment or inventory data is unavailable or invalid
    """
    try:
        shipment = get_shipment_by_id(
            shipment_reference
        )

        return _to_product_inventory_record(
            get_inventory_status(
                shipment.product_name
            )
        )

    except InvalidShipmentReferenceError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail=str(exc),
        ) from exc

    except ShipmentNotFoundError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc

    except InventoryNotFoundError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=INVENTORY_NOT_FOUND_DETAIL,
        ) from exc

    except ShipmentDataValidationError as exc:
        raise HTTPException(
            status_code=(
                status
                .HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail=str(exc),
        ) from exc

    except ShipmentDataUnavailableError as exc:
        raise HTTPException(
            status_code=(
                status
                .HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=str(exc),
        ) from exc

    except InventoryServiceError as exc:
        # The cause can name server files, so it is logged, not returned.
        logger.warning(
            "Inventory lookup failed for %s",
            shipment_reference,
            exc_info=exc,
        )

        raise HTTPException(
            status_code=(
                status
                .HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=INVENTORY_UNAVAILABLE_DETAIL,
        ) from exc
