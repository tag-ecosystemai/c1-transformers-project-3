import pytest

from backend.models.schemas import RiskLevel
from backend.services.supplier_service import (
    SupplierNotFoundError,
    clear_supplier_cache,
    find_alternative_supplier,
    get_compatible_supplier_categories,
    load_supplier_data,
)


@pytest.fixture(autouse=True)
def reset_supplier_cache():
    clear_supplier_cache()

    yield

    clear_supplier_cache()


def test_supplier_dataset_is_synthetic():
    dataframe = load_supplier_data()

    assert not dataframe.empty

    assert (
        dataframe["data_source"]
        == "SYNTHETIC_MVP"
    ).all()


def test_supplier_dataset_has_expected_shape():
    dataframe = load_supplier_data()

    assert len(dataframe) == 60
    assert dataframe["product_category"].nunique() == 33
    assert dataframe["supplier_country"].nunique() == 16


def test_cleats_maps_to_compatible_supplier_categories():
    categories = get_compatible_supplier_categories(
        "Cleats"
    )

    assert "cleats" in categories
    assert "men's footwear" in categories
    assert "sporting goods" in categories


def test_find_alternative_supplier_returns_candidates():
    result = find_alternative_supplier(
        category="Cleats",
        destination_country="Brasil",
        required_quantity=1,
        limit=3,
    )

    assert result.candidate_count >= 1
    assert result.alternatives
    assert result.data_source == "SYNTHETIC_MVP"

    assert (
        result.quantity_capacity_verified
        is False
    )


def test_recommended_supplier_is_not_high_risk():
    result = find_alternative_supplier(
        category="Cleats",
        destination_country="Brasil",
        required_quantity=1,
        limit=3,
    )

    assert result.recommended_supplier is not None

    assert (
        result.recommended_supplier
        .supplier_risk_level
        in {
            RiskLevel.LOW,
            RiskLevel.MEDIUM,
        }
    )


def test_supplier_candidates_use_compatible_categories():
    result = find_alternative_supplier(
        category="Cleats",
        destination_country="Brasil",
        required_quantity=1,
        limit=3,
    )

    compatible_categories = {
        "Men's Footwear",
        "Sporting Goods",
    }

    for supplier in result.alternatives:
        assert (
            supplier.product_category
            in compatible_categories
        )


def test_supplier_data_uses_zero_to_one_hundred_risk_scale():
    dataframe = load_supplier_data()

    assert (
        dataframe["supplier_risk_score"]
        .between(
            0,
            100,
            inclusive="both",
        )
        .all()
    )


def test_supplier_rates_use_zero_to_one_scale():
    dataframe = load_supplier_data()

    rate_columns = [
        "on_time_delivery_rate",
        "cancellation_rate",
        "quality_issue_rate",
        "capacity_utilization",
    ]

    for column in rate_columns:
        assert (
            dataframe[column]
            .between(
                0,
                1,
                inclusive="both",
            )
            .all()
        )


def test_quantity_is_context_not_verified_capacity():
    result = find_alternative_supplier(
        category="Cleats",
        destination_country="Brasil",
        required_quantity=1000,
        limit=3,
    )

    assert result.required_quantity == 1000

    assert (
        result.quantity_capacity_verified
        is False
    )

    assert (
        "cannot be validated"
        in result.limitation
    )


def test_unknown_category_raises():
    with pytest.raises(
        SupplierNotFoundError
    ):
        find_alternative_supplier(
            category="Unknown Category",
            destination_country="Brasil",
            required_quantity=1,
        )


def test_invalid_quantity_raises():
    with pytest.raises(ValueError):
        find_alternative_supplier(
            category="Cleats",
            destination_country="Brasil",
            required_quantity=0,
        )


def test_supplier_category_contracts_are_unique():
    dataframe = load_supplier_data()

    duplicates = dataframe.duplicated(
        subset=[
            "supplier_id",
            "product_category",
        ]
    )

    assert not duplicates.any()