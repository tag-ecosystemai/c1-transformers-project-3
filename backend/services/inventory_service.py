"""
Synthetic product-level inventory evidence.

The inventory dataset holds one record per product. A record is found
by exact product name, which is the only key the inventory and shipment
datasets share. The synthetic product_id is never used to join them.

What a record can and cannot support:

- It reports the stock figures recorded for a product.
- It does not show that stock is available to fulfil a shipment. The
  warehouse and supplier on each record were assigned at random when
  the data was generated, and the dataset has no as-of date.

Every lookup returns these limitations with the record. A dataset that
fails validation is rejected as a whole, so no figure is ever reported
from a file that contains inconsistent records.
"""

from functools import lru_cache
from pathlib import Path
import unicodedata

import pandas as pd

from backend.config import settings
from backend.exceptions import (
    InventoryNotFoundError,
    InventoryServiceError,
)
from backend.models.schemas import InventoryStatusResponse, RiskLevel


TEXT_COLUMNS = [
    "inventory_id",
    "product_id",
    "product_name",
    "category",
    "department",
    "warehouse_id",
    "warehouse_location",
    "warehouse_country",
    "supplier_id",
    "stockout_risk",
    "data_source",
]

QUANTITY_COLUMNS = [
    "current_stock",
    "reserved_stock",
    "available_stock",
    "daily_demand",
    "safety_stock",
    "reorder_point",
    "incoming_quantity",
]

NUMERIC_COLUMNS = [*QUANTITY_COLUMNS, "inventory_coverage_days"]

# expected_replenishment_date is required as a column but may be empty.
REQUIRED_COLUMNS = {
    *TEXT_COLUMNS,
    *NUMERIC_COLUMNS,
    "expected_replenishment_date",
}

SYNTHETIC_DATA_SOURCE = "SYNTHETIC_MVP"

# Recorded coverage is rounded to two decimal places.
COVERAGE_TOLERANCE = 0.02

MATCHED_ON = "product_name (exact, ignoring case and accents)"

STANDING_LIMITATIONS = [
    (
        "Inventory records are synthetic demonstration data and do not "
        "represent live warehouse stock."
    ),
    (
        "The record describes the product, not this shipment: it was "
        "matched on product name only and does not show that stock is "
        "available to fulfil the shipment."
    ),
    (
        "The warehouse and supplier on the record were assigned at "
        "random when the data was generated and are unrelated to the "
        "shipment's origin, destination or supplier."
    ),
    (
        "The inventory dataset has no as-of date, so stock levels and "
        "any expected replenishment date cannot be related to the "
        "shipment's dates."
    ),
]


def normalize_text(value: str) -> str:
    """
    Normalize text for case-insensitive and accent-insensitive matching.
    """
    normalized = unicodedata.normalize("NFKD", str(value).strip())

    return "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    ).casefold()


def calculate_stockout_risk(
    available_stock: int,
    safety_stock: int,
    inventory_coverage_days: float,
) -> RiskLevel:
    """
    The rule that classified stockout risk when the dataset was
    generated. Used only to check that recorded classifications are
    consistent with the recorded quantities.

    HIGH: available stock is at or below safety stock.
    MEDIUM: above safety stock, with coverage of seven days or less.
    LOW: above safety stock, with coverage of more than seven days.
    """
    if available_stock <= safety_stock:
        return RiskLevel.HIGH

    if inventory_coverage_days <= 7:
        return RiskLevel.MEDIUM

    return RiskLevel.LOW


def _reject(invalid: pd.Series, problem: str) -> None:
    """Reject the dataset when any record is marked invalid."""
    if invalid.any():
        raise InventoryServiceError(
            f"The inventory dataset has {int(invalid.sum())} record(s) "
            f"where {problem}."
        )


def _validate(dataframe: pd.DataFrame) -> pd.DataFrame:
    """
    Check every record and return the dataset in normalized form.

    Nothing is corrected: a dataset with any missing, malformed or
    inconsistent record is rejected.
    """
    dataframe = dataframe.copy()

    for column in TEXT_COLUMNS:
        dataframe[column] = dataframe[column].astype("string").str.strip()
        _reject(
            dataframe[column].isna() | dataframe[column].eq(""),
            f"'{column}' is missing",
        )

    for column in NUMERIC_COLUMNS:
        dataframe[column] = pd.to_numeric(dataframe[column], errors="coerce")
        _reject(
            dataframe[column].isna(),
            f"'{column}' is missing or not a number",
        )
        _reject(dataframe[column] < 0, f"'{column}' is negative")

    for column in QUANTITY_COLUMNS:
        _reject(
            dataframe[column] % 1 != 0,
            f"'{column}' is not a whole number",
        )
        dataframe[column] = dataframe[column].astype(int)

    _reject(dataframe["daily_demand"] <= 0, "'daily_demand' is not positive")
    _reject(
        dataframe["reserved_stock"] > dataframe["current_stock"],
        "'reserved_stock' exceeds 'current_stock'",
    )

    expected_available = (
        dataframe["current_stock"] - dataframe["reserved_stock"]
    )
    _reject(
        dataframe["available_stock"] != expected_available,
        "'available_stock' is not current stock minus reserved stock",
    )

    expected_coverage = expected_available / dataframe["daily_demand"]
    _reject(
        (dataframe["inventory_coverage_days"] - expected_coverage).abs()
        > COVERAGE_TOLERANCE,
        "'inventory_coverage_days' is not available stock divided by "
        "daily demand",
    )

    dataframe["data_source"] = dataframe["data_source"].str.upper()
    _reject(
        dataframe["data_source"] != SYNTHETIC_DATA_SOURCE,
        f"'data_source' is not '{SYNTHETIC_DATA_SOURCE}'",
    )

    dataframe["stockout_risk"] = dataframe["stockout_risk"].str.upper()
    _reject(
        ~dataframe["stockout_risk"].isin(
            [level.value for level in RiskLevel]
        ),
        "'stockout_risk' is not a supported risk level",
    )

    expected_risk = dataframe.apply(
        lambda row: calculate_stockout_risk(
            available_stock=row["available_stock"],
            safety_stock=row["safety_stock"],
            inventory_coverage_days=row["inventory_coverage_days"],
        ).value,
        axis=1,
    )
    _reject(
        dataframe["stockout_risk"] != expected_risk,
        "'stockout_risk' does not follow from the recorded quantities",
    )

    raw_dates = dataframe["expected_replenishment_date"]
    has_date = raw_dates.notna() & raw_dates.astype(str).str.strip().ne("")
    dataframe["_replenishment_date"] = pd.to_datetime(
        raw_dates.where(has_date),
        format="ISO8601",
        errors="coerce",
    )
    _reject(
        has_date & dataframe["_replenishment_date"].isna(),
        "'expected_replenishment_date' is not a valid date",
    )

    dataframe["_normalized_product_name"] = dataframe["product_name"].map(
        normalize_text
    )

    # One record per product is what makes a product-name match exact.
    for column, label in [
        ("inventory_id", "inventory_id"),
        ("product_id", "product_id"),
        ("_normalized_product_name", "product_name"),
    ]:
        _reject(
            dataframe[column].duplicated(keep=False),
            f"'{label}' is duplicated",
        )

    return dataframe


@lru_cache(maxsize=1)
def load_inventory_data() -> pd.DataFrame:
    """
    Load, validate and cache the synthetic inventory dataset.
    """
    inventory_path = Path(settings.inventory_data_path)

    if not inventory_path.exists():
        raise InventoryServiceError(
            f"Inventory data was not found at: {inventory_path}"
        )

    try:
        dataframe = pd.read_csv(inventory_path, low_memory=False)
    except Exception as exc:
        raise InventoryServiceError(
            f"Unable to load inventory data from '{inventory_path}': {exc}"
        ) from exc

    missing_columns = REQUIRED_COLUMNS - set(dataframe.columns)

    if missing_columns:
        raise InventoryServiceError(
            "The inventory dataset is missing columns: "
            + ", ".join(sorted(missing_columns))
        )

    if dataframe.empty:
        raise InventoryServiceError("The inventory dataset is empty.")

    return _validate(dataframe)


def _row_to_inventory_status(row: pd.Series) -> InventoryStatusResponse:
    """
    Convert one validated inventory record into the response schema.
    """
    replenishment_date = row["_replenishment_date"]
    available_stock = int(row["available_stock"])

    return InventoryStatusResponse(
        inventory_id=row["inventory_id"],
        product_id=row["product_id"],
        product_name=row["product_name"],
        category=row["category"],
        department=row["department"],
        warehouse_id=row["warehouse_id"],
        warehouse_location=row["warehouse_location"],
        warehouse_country=row["warehouse_country"],
        supplier_id=row["supplier_id"],
        current_stock=int(row["current_stock"]),
        reserved_stock=int(row["reserved_stock"]),
        available_stock=available_stock,
        daily_demand=int(row["daily_demand"]),
        safety_stock=int(row["safety_stock"]),
        reorder_point=int(row["reorder_point"]),
        incoming_quantity=int(row["incoming_quantity"]),
        expected_replenishment_date=(
            None if pd.isna(replenishment_date) else replenishment_date.date()
        ),
        inventory_coverage_days=float(row["inventory_coverage_days"]),
        stockout_risk=RiskLevel(row["stockout_risk"]),
        below_safety_stock=available_stock <= int(row["safety_stock"]),
        below_reorder_point=available_stock <= int(row["reorder_point"]),
        matched_on=MATCHED_ON,
        data_source=row["data_source"],
        limitations=list(STANDING_LIMITATIONS),
    )


def get_inventory_status(product_name: str) -> InventoryStatusResponse:
    """
    Return the synthetic inventory record for an exact product name.

    Matching is exact after case and accent normalization. Fuzzy and
    category-level matching are deliberately excluded: every shipment
    product has exactly one inventory record with the same name.

    Raises InventoryNotFoundError when no record matches, and
    InventoryServiceError when the product name is empty or the dataset
    cannot be loaded or fails validation.
    """
    if not isinstance(product_name, str) or not product_name.strip():
        raise InventoryServiceError(
            "A product name is required to look up inventory."
        )

    dataframe = load_inventory_data()

    matches = dataframe.loc[
        dataframe["_normalized_product_name"] == normalize_text(product_name)
    ]

    if matches.empty:
        raise InventoryNotFoundError(
            "No synthetic inventory record was found for product "
            f"'{product_name}'."
        )

    return _row_to_inventory_status(matches.iloc[0])


def clear_inventory_cache() -> None:
    """
    Clear cached inventory data for tests or dataset replacement.
    """
    load_inventory_data.cache_clear()
