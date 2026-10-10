from datetime import date

import pandas as pd
import pytest

from backend.config import PROJECT_ROOT, settings
from backend.exceptions import (
    InventoryNotFoundError,
    InventoryServiceError,
)
from backend.models.schemas import InventoryStatusResponse, RiskLevel
from backend.services.inventory_service import (
    calculate_stockout_risk,
    clear_inventory_cache,
    get_inventory_status,
    load_inventory_data,
    normalize_text,
)


REAL_INVENTORY_PATH = (
    PROJECT_ROOT / "data" / "processed" / "inventory_tool_data.csv"
)
REAL_SHIPMENT_PATH = (
    PROJECT_ROOT / "data" / "processed" / "shipment_tool_data.csv"
)

COLUMNS = [
    "inventory_id",
    "product_id",
    "product_name",
    "category",
    "department",
    "warehouse_id",
    "warehouse_location",
    "warehouse_country",
    "supplier_id",
    "current_stock",
    "reserved_stock",
    "available_stock",
    "daily_demand",
    "safety_stock",
    "reorder_point",
    "incoming_quantity",
    "expected_replenishment_date",
    "inventory_coverage_days",
    "stockout_risk",
    "data_source",
]


def make_record(**overrides):
    """A valid LOW-risk inventory record with fractional coverage."""
    record = {
        "inventory_id": "INV-LOW",
        "product_id": "PROD-LOW",
        "product_name": "Healthy Product",
        "category": "Cleats",
        "department": "Footwear",
        "warehouse_id": "WH-020",
        "warehouse_location": "São Paulo",
        "warehouse_country": "Brazil",
        "supplier_id": "SUP001",
        "current_stock": 1000,
        "reserved_stock": 195,
        "available_stock": 805,
        "daily_demand": 47,
        "safety_stock": 200,
        "reorder_point": 450,
        "incoming_quantity": 500,
        "expected_replenishment_date": "2017-06-23",
        "inventory_coverage_days": 17.13,
        "stockout_risk": "LOW",
        "data_source": "SYNTHETIC_MVP",
    }
    record.update(overrides)
    return record


RECORDS = [
    make_record(),
    make_record(
        inventory_id="INV-MEDIUM",
        product_id="PROD-MEDIUM",
        product_name="Limited Product",
        current_stock=400,
        reserved_stock=100,
        available_stock=300,
        daily_demand=50,
        inventory_coverage_days=6.0,
        stockout_risk="MEDIUM",
    ),
    make_record(
        inventory_id="INV-HIGH",
        product_id="PROD-HIGH",
        product_name="Exposed Product",
        current_stock=300,
        reserved_stock=100,
        available_stock=200,
        daily_demand=50,
        safety_stock=250,
        reorder_point=500,
        incoming_quantity=0,
        expected_replenishment_date=None,
        inventory_coverage_days=4.0,
        stockout_risk="HIGH",
    ),
]


@pytest.fixture
def write_inventory(tmp_path, monkeypatch):
    """
    Point the service at a temporary inventory file and return a
    function that writes the given records to it.
    """
    path = tmp_path / "inventory_tool_data.csv"
    monkeypatch.setattr(settings, "inventory_data_path", path)
    clear_inventory_cache()

    def write(records, columns=COLUMNS):
        pd.DataFrame(records, columns=columns).to_csv(path, index=False)
        clear_inventory_cache()
        return path

    yield write

    clear_inventory_cache()


@pytest.fixture
def inventory(write_inventory):
    return write_inventory(RECORDS)


# ============================================================
# LOOKUP
# ============================================================


def test_lookup_returns_the_recorded_values(inventory):
    result = get_inventory_status("Healthy Product")

    assert isinstance(result, InventoryStatusResponse)
    assert result.inventory_id == "INV-LOW"
    assert result.product_name == "Healthy Product"
    assert result.category == "Cleats"
    assert result.current_stock == 1000
    assert result.reserved_stock == 195
    assert result.available_stock == 805
    assert result.daily_demand == 47
    assert result.safety_stock == 200
    assert result.reorder_point == 450
    assert result.incoming_quantity == 500
    assert result.expected_replenishment_date == date(2017, 6, 23)
    assert result.stockout_risk == RiskLevel.LOW
    assert result.data_source == "SYNTHETIC_MVP"


def test_fractional_coverage_is_not_rounded(inventory):
    result = get_inventory_status("Healthy Product")

    assert result.inventory_coverage_days == 17.13


def test_lookup_ignores_case_accents_and_padding(write_inventory):
    write_inventory([make_record(product_name="Café Runner")])

    result = get_inventory_status("  CAFE RUNNER ")

    assert result.inventory_id == "INV-LOW"
    assert result.product_name == "Café Runner"


def test_result_states_how_the_record_was_matched(inventory):
    result = get_inventory_status("Healthy Product")

    assert result.matched_on.startswith("product_name")


def test_partial_product_names_do_not_match(inventory):
    with pytest.raises(InventoryNotFoundError):
        get_inventory_status("Healthy")


def test_synthetic_product_id_is_not_a_lookup_key(inventory):
    with pytest.raises(InventoryNotFoundError):
        get_inventory_status("PROD-LOW")


def test_unknown_product_raises_not_found(inventory):
    with pytest.raises(InventoryNotFoundError, match="Unknown Product"):
        get_inventory_status("Unknown Product")


def test_not_found_is_an_inventory_service_error(inventory):
    with pytest.raises(InventoryServiceError):
        get_inventory_status("Unknown Product")


@pytest.mark.parametrize("product_name", ["", "   ", None, 153440])
def test_missing_product_name_raises_service_error(inventory, product_name):
    with pytest.raises(InventoryServiceError, match="product name"):
        get_inventory_status(product_name)


def test_medium_risk_record(inventory):
    result = get_inventory_status("Limited Product")

    assert result.stockout_risk == RiskLevel.MEDIUM
    assert result.below_safety_stock is False
    assert result.below_reorder_point is True


def test_high_risk_record_without_replenishment(inventory):
    result = get_inventory_status("Exposed Product")

    assert result.stockout_risk == RiskLevel.HIGH
    assert result.below_safety_stock is True
    assert result.below_reorder_point is True
    assert result.incoming_quantity == 0
    assert result.expected_replenishment_date is None


# ============================================================
# LIMITATIONS
# ============================================================


def test_every_result_carries_the_standing_limitations(inventory):
    limitations = " ".join(
        get_inventory_status("Healthy Product").limitations
    )

    assert "synthetic demonstration data" in limitations
    assert "not this shipment" in limitations
    assert "does not show that stock is available" in limitations
    assert "assigned at random" in limitations
    assert "no as-of date" in limitations


def test_results_do_not_share_a_limitations_list(inventory):
    first = get_inventory_status("Healthy Product")
    first.limitations.append("changed by a caller")

    second = get_inventory_status("Healthy Product")

    assert "changed by a caller" not in second.limitations


def test_result_makes_no_shipment_specific_claim():
    fields = set(InventoryStatusResponse.model_fields)

    assert not {
        "destination_country",
        "destination_country_match",
        "shipment_id",
    } & fields


# ============================================================
# DATASET LOADING AND VALIDATION
# ============================================================


def test_missing_file_raises_service_error(write_inventory):
    with pytest.raises(InventoryServiceError, match="not found"):
        get_inventory_status("Healthy Product")


def test_unreadable_file_raises_service_error(write_inventory):
    write_inventory(RECORDS).write_text("", encoding="utf-8")
    clear_inventory_cache()

    with pytest.raises(InventoryServiceError, match="Unable to load"):
        load_inventory_data()


def test_dataset_without_records_raises_service_error(write_inventory):
    write_inventory([])

    with pytest.raises(InventoryServiceError, match="empty"):
        load_inventory_data()


def test_missing_column_raises_service_error(write_inventory):
    write_inventory(
        RECORDS,
        columns=[c for c in COLUMNS if c != "daily_demand"],
    )

    with pytest.raises(InventoryServiceError, match="daily_demand"):
        load_inventory_data()


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"product_name": None}, "'product_name' is missing"),
        ({"warehouse_id": "  "}, "'warehouse_id' is missing"),
        ({"current_stock": None}, "'current_stock' is missing"),
        ({"daily_demand": "many"}, "'daily_demand' is missing or not"),
        ({"safety_stock": -1}, "'safety_stock' is negative"),
        ({"reorder_point": 450.5}, "'reorder_point' is not a whole"),
        (
            {
                "daily_demand": 0,
                "inventory_coverage_days": 0,
            },
            "'daily_demand' is not positive",
        ),
        (
            {"reserved_stock": 1200},
            "'reserved_stock' exceeds 'current_stock'",
        ),
        ({"available_stock": 804}, "'available_stock' is not current"),
        (
            {"inventory_coverage_days": 99.0},
            "'inventory_coverage_days' is not available",
        ),
        ({"stockout_risk": "HIGH"}, "'stockout_risk' does not follow"),
        ({"stockout_risk": "SEVERE"}, "'stockout_risk' is not a supported"),
        ({"data_source": "ERP"}, "'data_source' is not 'SYNTHETIC_MVP'"),
        (
            {"expected_replenishment_date": "next week"},
            "'expected_replenishment_date' is not a valid date",
        ),
    ],
)
def test_malformed_record_rejects_the_dataset(
    write_inventory,
    overrides,
    problem,
):
    write_inventory([make_record(**overrides), *RECORDS[1:]])

    with pytest.raises(InventoryServiceError, match=problem):
        get_inventory_status("Limited Product")


@pytest.mark.parametrize(
    ("overrides", "column"),
    [
        (
            {"product_id": "PROD-OTHER", "inventory_id": "INV-OTHER"},
            "product_name",
        ),
        (
            {"product_name": "Other", "inventory_id": "INV-OTHER"},
            "product_id",
        ),
        (
            {"product_name": "Other", "product_id": "PROD-OTHER"},
            "inventory_id",
        ),
        (
            {
                "product_name": "HEALTHY PRODUCT",
                "product_id": "PROD-OTHER",
                "inventory_id": "INV-OTHER",
            },
            "product_name",
        ),
    ],
)
def test_duplicate_records_reject_the_dataset(
    write_inventory,
    overrides,
    column,
):
    write_inventory([*RECORDS, make_record(**overrides)])

    with pytest.raises(
        InventoryServiceError,
        match=f"'{column}' is duplicated",
    ):
        load_inventory_data()


def test_dataset_is_loaded_once_and_reloaded_after_clearing(write_inventory):
    path = write_inventory(RECORDS)
    assert get_inventory_status("Healthy Product").current_stock == 1000

    restocked = make_record(
        current_stock=1195,
        available_stock=1000,
        inventory_coverage_days=21.28,
    )
    pd.DataFrame([restocked], columns=COLUMNS).to_csv(path, index=False)

    assert get_inventory_status("Healthy Product").current_stock == 1000

    clear_inventory_cache()

    assert get_inventory_status("Healthy Product").current_stock == 1195


# ============================================================
# HELPERS
# ============================================================


@pytest.mark.parametrize(
    ("available_stock", "safety_stock", "coverage", "expected"),
    [
        (200, 250, 4.0, RiskLevel.HIGH),
        (250, 250, 9.0, RiskLevel.HIGH),
        (300, 200, 7.0, RiskLevel.MEDIUM),
        (800, 200, 7.01, RiskLevel.LOW),
    ],
)
def test_stockout_risk_rule(available_stock, safety_stock, coverage, expected):
    assert calculate_stockout_risk(
        available_stock=available_stock,
        safety_stock=safety_stock,
        inventory_coverage_days=coverage,
    ) == expected


def test_normalize_text_ignores_case_accents_and_padding():
    assert normalize_text("  São Paulo ") == "sao paulo"


# ============================================================
# COMMITTED DATASET
# ============================================================


@pytest.fixture
def real_inventory(monkeypatch):
    monkeypatch.setattr(settings, "inventory_data_path", REAL_INVENTORY_PATH)
    clear_inventory_cache()

    yield load_inventory_data()

    clear_inventory_cache()


def test_committed_dataset_is_valid(real_inventory):
    assert len(real_inventory) == 73
    assert real_inventory["product_name"].is_unique
    assert (real_inventory["data_source"] == "SYNTHETIC_MVP").all()


def test_committed_dataset_keeps_fractional_coverage(real_inventory):
    result = get_inventory_status(
        "Merrell Men's All Out Flash Trail Running Sho"
    )

    assert result.inventory_id == "INV-000001"
    assert result.available_stock == 303
    assert result.daily_demand == 47
    assert result.inventory_coverage_days == 6.45


def test_every_shipment_product_has_one_matching_inventory_record(
    real_inventory,
):
    """
    The product-name match is only defensible while every shipment
    product has exactly one inventory record that agrees on category
    and department.
    """
    products = pd.read_csv(
        REAL_SHIPMENT_PATH,
        usecols=["product_name", "category", "department"],
    ).drop_duplicates()

    assert products["product_name"].is_unique

    for product in products.itertuples():
        record = get_inventory_status(product.product_name)

        assert record.category == product.category.strip()
        assert record.department == product.department.strip()
