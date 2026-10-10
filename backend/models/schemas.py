from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# ENUMS
# ============================================================


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ToolCallStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"


# ============================================================
# SHIPMENT SCHEMAS
# ============================================================


class ShipmentBase(BaseModel):
    """
    Leakage-safe shipment information returned by the Shipment Tool.

    The fields in this schema correspond to the columns available in
    data/processed/shipment_tool_data.csv.
    """

    model_config = ConfigDict(
        extra="ignore",
        str_strip_whitespace=True,
    )

    order_id: int = Field(
        ...,
        description="DataCo order identifier",
    )

    shipment_id: int = Field(
        ...,
        description="Unique order-item-level shipment identifier",
    )

    shipment_reference: str = Field(
        ...,
        pattern=r"^SHP-\d+$",
        description="Public shipment reference in SHP-<shipment_id> format",
        examples=["SHP-153440"],
    )

    product_name: str = Field(
        ...,
        description="Name of the product being shipped",
    )

    category: str = Field(
        ...,
        description="Product category",
    )

    department: str = Field(
        ...,
        description="Department associated with the product",
    )

    market: str = Field(
        ...,
        description="Commercial market associated with the shipment",
    )

    customer_country: str = Field(
        ...,
        description="Country associated with the customer",
    )

    destination_country: str = Field(
        ...,
        description="Shipment destination country",
    )

    destination_region: str = Field(
        ...,
        description="Shipment destination region",
    )

    destination_state: str = Field(
        ...,
        description="Shipment destination state or province",
    )

    destination_city: str = Field(
        ...,
        description="Shipment destination city",
    )

    shipping_mode: str = Field(
        ...,
        description="Shipment service mode",
    )

    scheduled_shipping_days: int = Field(
        ...,
        ge=0,
        description="Planned number of days for shipment delivery",
    )

    quantity: int = Field(
        ...,
        ge=0,
        description="Quantity of products included in the shipment record",
    )

    product_price: float = Field(
        ...,
        ge=0,
        description="Unit price of the product",
    )

    sales: float = Field(
        ...,
        ge=0,
        description="Sales value associated with the shipment record",
    )

    discount: float = Field(
        ...,
        ge=0,
        description="Discount value associated with the shipment record",
    )

    order_date: datetime = Field(
        ...,
        description="Date and time when the order was placed",
    )

    latitude: float = Field(
        ...,
        ge=-90,
        le=90,
        description="Latitude available in the shipment dataset",
    )

    longitude: float = Field(
        ...,
        ge=-180,
        le=180,
        description="Longitude available in the shipment dataset",
    )

    historical_product_delay_rate: float = Field(
        ...,
        ge=0,
        le=1,
        description="Historical delay rate associated with the product",
    )

    historical_market_delay_rate: float = Field(
        ...,
        ge=0,
        le=1,
        description="Historical delay rate associated with the market",
    )

    historical_shipping_mode_delay_rate: float = Field(
        ...,
        ge=0,
        le=1,
        description="Historical delay rate associated with the shipping mode",
    )


class ShipmentResponse(ShipmentBase):
    """
    API response returned for a successful shipment lookup.
    """

    pass


# ============================================================
# MACHINE-LEARNING PREDICTION SCHEMAS
# ============================================================


class PredictionResponse(BaseModel):
    shipment_id: str = Field(
        ...,
        description="Public shipment reference",
        examples=["SHP-153440"],
    )

    delay_probability: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Model-estimated probability of shipment delay",
    )

    risk_level: RiskLevel = Field(
        ...,
        description="Operational risk classification",
    )

    requires_investigation: bool = Field(
        ...,
        description=(
            "Indicates whether the shipment should proceed to "
            "agent investigation"
        ),
    )


# ============================================================
# INVENTORY SCHEMAS
# ============================================================


class InventoryStatusResponse(BaseModel):
    """
    The synthetic inventory record held for one product.

    The record describes a product, not a shipment: it does not show
    that stock is available to fulfil any particular shipment. Every
    quantity is taken from the inventory dataset as recorded.
    """

    inventory_id: str = Field(
        ...,
        description="Synthetic inventory-record identifier",
    )

    product_id: str = Field(
        ...,
        description=(
            "Synthetic product identifier. It exists only in the "
            "inventory dataset and is not a shipment join key"
        ),
    )

    product_name: str = Field(
        ...,
        description="Product the inventory record describes",
    )

    category: str = Field(
        ...,
        description="Product category",
    )

    department: str = Field(
        ...,
        description="Product department",
    )

    warehouse_id: str = Field(
        ...,
        description=(
            "Synthetic warehouse identifier, assigned at random and "
            "unrelated to any shipment"
        ),
    )

    warehouse_location: str = Field(
        ...,
        description="Location of the synthetic warehouse",
    )

    warehouse_country: str = Field(
        ...,
        description="Country of the synthetic warehouse",
    )

    supplier_id: str = Field(
        ...,
        description=(
            "Synthetic supplier identifier, assigned at random and "
            "unrelated to any shipment"
        ),
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

    reorder_point: int = Field(
        ...,
        ge=0,
        description="Reorder-point threshold in units",
    )

    incoming_quantity: int = Field(
        ...,
        ge=0,
        description="Units recorded as incoming",
    )

    expected_replenishment_date: Optional[date] = Field(
        default=None,
        description="Expected replenishment date when one is recorded",
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

    below_reorder_point: bool = Field(
        ...,
        description=(
            "Whether available stock is at or below the reorder point"
        ),
    )

    matched_on: str = Field(
        ...,
        description="How the record was matched to the requested product",
    )

    data_source: str = Field(
        ...,
        description="Source label of the inventory record",
    )

    limitations: List[str] = Field(
        default_factory=list,
        description="What this inventory evidence does not establish",
    )


# ============================================================
# AGENT EVIDENCE AND BRIEFING SCHEMAS
# ============================================================


class ToolEvidence(BaseModel):
    shipment_summary: Optional[str] = Field(
        default=None,
        description="Summary produced from the Shipment Tool response",
    )

    historical_delay_summary: Optional[str] = Field(
        default=None,
        description=(
            "Historical delay rates for the shipment's product, market "
            "and shipping mode"
        ),
    )

    weather_summary: Optional[str] = Field(
        default=None,
        description="Evidence returned by the Weather Tool",
    )

    supplier_status: Optional[str] = Field(
        default=None,
        description="Evidence returned by the Supplier Tool",
    )

    inventory_summary: Optional[str] = Field(
        default=None,
        description=(
            "Product-level inventory record for the shipment's product. "
            "It does not show that stock is available for this shipment"
        ),
    )

    inventory_coverage_days: Optional[int] = Field(
        default=None,
        ge=0,
        description="Available inventory coverage measured in days",
    )


class ToolCall(BaseModel):
    """
    One tool call made during an investigation, kept as evidence.
    """

    tool: str = Field(
        ...,
        description="Name of the tool that was called",
        examples=["get_shipment"],
    )

    input: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments passed to the tool",
    )

    output: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Data returned by the tool; empty when the call failed",
    )

    status: ToolCallStatus = Field(
        ...,
        description="Whether the tool call succeeded",
    )

    error: Optional[str] = Field(
        default=None,
        description="Error message when the tool call failed",
    )


class DisruptionBriefingResponse(BaseModel):
    shipment_id: str = Field(
        ...,
        description="Public shipment reference",
        examples=["SHP-153440"],
    )

    risk_level: RiskLevel

    delay_probability: float = Field(
        ...,
        ge=0.0,
        le=1.0,
    )

    evidence: ToolEvidence

    rag_policy_citations: List[str] = Field(
        default_factory=list,
        description="Operational procedure references retrieved by RAG",
    )

    summary: str = Field(
        ...,
        description="Executive summary of the disruption investigation",
    )

    recommended_actions: List[str] = Field(
        default_factory=list,
        description="Recommended actions for logistics operators",
    )

    tool_trace: List[ToolCall] = Field(
        default_factory=list,
        description="Tool calls made during the investigation, in order",
    )

    limitations: List[str] = Field(
        default_factory=list,
        description=(
            "Evidence that could not be collected and other caveats "
            "on this briefing"
        ),
    )