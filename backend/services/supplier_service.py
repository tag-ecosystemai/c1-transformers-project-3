from functools import lru_cache
from pathlib import Path
import unicodedata

import pandas as pd

from backend.config import settings
from backend.models.schemas import (
    RiskLevel,
    SupplierCandidate,
    SupplierRecommendation,
)


class SupplierServiceError(RuntimeError):
    """
    Raised when supplier data cannot be loaded or validated.
    """


class SupplierNotFoundError(SupplierServiceError):
    """
    Raised when no category-compatible supplier can be found.
    """


REQUIRED_COLUMNS = {
    "supplier_id",
    "supplier_name",
    "supplier_country",
    "product_category",
    "average_lead_time_days",
    "on_time_delivery_rate",
    "cancellation_rate",
    "quality_issue_rate",
    "capacity_utilization",
    "supplier_risk_score",
    "supplier_risk_level",
    "data_source",
}


CATEGORY_ALIASES = {
    "cleats": {
        "men's footwear",
        "sporting goods",
    },
}


def normalize_text(value: str) -> str:
    """
    Normalize text for case-insensitive and accent-insensitive matching.
    """
    normalized = unicodedata.normalize(
        "NFKD",
        str(value).strip(),
    )

    return "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    ).casefold()


def get_compatible_supplier_categories(
    category: str,
) -> set:
    """
    Return normalized supplier categories compatible with a shipment
    category.

    Exact matching is always included. Additional mappings are
    explicitly defined in CATEGORY_ALIASES.
    """
    normalized_category = normalize_text(category)

    if not normalized_category:
        raise ValueError(
            "The product category cannot be empty."
        )

    compatible_categories = {
        normalized_category,
    }

    aliases = CATEGORY_ALIASES.get(
        normalized_category,
        set(),
    )

    compatible_categories.update(
        normalize_text(alias)
        for alias in aliases
    )

    return compatible_categories


@lru_cache(maxsize=1)
def load_supplier_data() -> pd.DataFrame:
    """
    Load, validate, normalize, and cache the synthetic supplier dataset.
    """
    supplier_path = Path(
        settings.supplier_data_path
    )

    if not supplier_path.exists():
        raise SupplierServiceError(
            "Supplier data was not found at: "
            f"{supplier_path}"
        )

    try:
        dataframe = pd.read_csv(
            supplier_path,
            low_memory=False,
        )
    except Exception as exc:
        raise SupplierServiceError(
            "Unable to load supplier data from "
            f"'{supplier_path}': {exc}"
        ) from exc

    if dataframe.empty:
        raise SupplierServiceError(
            "The supplier dataset is empty."
        )

    missing_columns = (
        REQUIRED_COLUMNS
        - set(dataframe.columns)
    )

    if missing_columns:
        raise SupplierServiceError(
            "The supplier dataset is missing columns: "
            + ", ".join(
                sorted(missing_columns)
            )
        )

    dataframe = dataframe.copy()

    string_columns = [
        "supplier_id",
        "supplier_name",
        "supplier_country",
        "product_category",
        "supplier_risk_level",
        "data_source",
    ]

    numeric_columns = [
        "average_lead_time_days",
        "on_time_delivery_rate",
        "cancellation_rate",
        "quality_issue_rate",
        "capacity_utilization",
        "supplier_risk_score",
    ]

    for column in string_columns:
        dataframe[column] = (
            dataframe[column]
            .astype("string")
            .str.strip()
        )

    for column in numeric_columns:
        dataframe[column] = pd.to_numeric(
            dataframe[column],
            errors="coerce",
        )

    missing_counts = (
        dataframe[list(REQUIRED_COLUMNS)]
        .isna()
        .sum()
    )

    missing_counts = missing_counts[
        missing_counts > 0
    ]

    if not missing_counts.empty:
        raise SupplierServiceError(
            "The supplier dataset contains missing or invalid "
            "required values: "
            + ", ".join(
                f"{column}={int(count)}"
                for column, count
                in missing_counts.items()
            )
        )

    empty_string_counts = {
        column: int(
            dataframe[column]
            .astype(str)
            .str.strip()
            .eq("")
            .sum()
        )
        for column in string_columns
    }

    empty_string_counts = {
        column: count
        for column, count in empty_string_counts.items()
        if count > 0
    }

    if empty_string_counts:
        raise SupplierServiceError(
            "The supplier dataset contains empty required text "
            "values: "
            + ", ".join(
                f"{column}={count}"
                for column, count
                in empty_string_counts.items()
            )
        )

    dataframe["data_source"] = (
        dataframe["data_source"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    if not dataframe["data_source"].eq(
        "SYNTHETIC_MVP"
    ).all():
        raise SupplierServiceError(
            "Every supplier record must be labelled "
            "'SYNTHETIC_MVP'."
        )

    rate_columns = [
        "on_time_delivery_rate",
        "cancellation_rate",
        "quality_issue_rate",
        "capacity_utilization",
    ]

    for column in rate_columns:
        valid_rates = dataframe[column].between(
            0,
            1,
            inclusive="both",
        )

        if not valid_rates.all():
            invalid_count = int(
                (~valid_rates).sum()
            )

            raise SupplierServiceError(
                f"Column '{column}' contains "
                f"{invalid_count} value(s) outside the "
                "range 0 to 1."
            )

    valid_lead_times = (
        dataframe["average_lead_time_days"] > 0
    )

    if not valid_lead_times.all():
        invalid_count = int(
            (~valid_lead_times).sum()
        )

        raise SupplierServiceError(
            "'average_lead_time_days' contains "
            f"{invalid_count} non-positive value(s)."
        )

    valid_risk_scores = dataframe[
        "supplier_risk_score"
    ].between(
        0,
        100,
        inclusive="both",
    )

    if not valid_risk_scores.all():
        invalid_count = int(
            (~valid_risk_scores).sum()
        )

        raise SupplierServiceError(
            "'supplier_risk_score' contains "
            f"{invalid_count} value(s) outside the "
            "range 0 to 100."
        )

    dataframe["supplier_risk_level"] = (
        dataframe["supplier_risk_level"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    valid_risk_levels = {
        level.value
        for level in RiskLevel
    }

    invalid_risk_levels = (
        set(
            dataframe["supplier_risk_level"]
        )
        - valid_risk_levels
    )

    if invalid_risk_levels:
        raise SupplierServiceError(
            "The supplier dataset contains unsupported "
            "risk levels: "
            + ", ".join(
                sorted(invalid_risk_levels)
            )
        )

    duplicate_contracts = dataframe.duplicated(
        subset=[
            "supplier_id",
            "product_category",
        ],
        keep=False,
    )

    if duplicate_contracts.any():
        duplicate_count = int(
            duplicate_contracts.sum()
        )

        raise SupplierServiceError(
            "The supplier dataset contains "
            f"{duplicate_count} duplicate "
            "supplier-category record(s)."
        )

    dataframe["_normalized_category"] = (
        dataframe["product_category"]
        .map(normalize_text)
    )

    dataframe["_normalized_country"] = (
        dataframe["supplier_country"]
        .map(normalize_text)
    )

    return dataframe


def row_to_supplier_candidate(
    row: pd.Series,
) -> SupplierCandidate:
    """
    Convert one supplier-data row into the response schema.
    """
    return SupplierCandidate(
        supplier_id=str(
            row["supplier_id"]
        ),
        supplier_name=str(
            row["supplier_name"]
        ),
        supplier_country=str(
            row["supplier_country"]
        ),
        product_category=str(
            row["product_category"]
        ),
        average_lead_time_days=float(
            row["average_lead_time_days"]
        ),
        on_time_delivery_rate=float(
            row["on_time_delivery_rate"]
        ),
        cancellation_rate=float(
            row["cancellation_rate"]
        ),
        quality_issue_rate=float(
            row["quality_issue_rate"]
        ),
        capacity_utilization=float(
            row["capacity_utilization"]
        ),
        supplier_risk_score=float(
            row["supplier_risk_score"]
        ),
        supplier_risk_level=RiskLevel(
            str(
                row["supplier_risk_level"]
            ).upper()
        ),
        data_source=str(
            row["data_source"]
        ),
    )


def rank_supplier_candidates(
    dataframe: pd.DataFrame,
    destination_country: str,
) -> pd.DataFrame:
    """
    Rank category-compatible suppliers.

    Ranking priority:
    1. Supplier country matches the destination country.
    2. Lower supplier risk score.
    3. Lower supplier risk level.
    4. Shorter average lead time.
    5. Higher on-time delivery rate.
    6. Lower cancellation rate.
    7. Lower quality-issue rate.
    8. Lower capacity utilization.
    """
    ranked = dataframe.copy()

    normalized_destination = normalize_text(
        destination_country
    )

    ranked["_country_match"] = (
        ranked["_normalized_country"]
        == normalized_destination
    )

    risk_priority = {
        RiskLevel.LOW.value: 0,
        RiskLevel.MEDIUM.value: 1,
        RiskLevel.HIGH.value: 2,
    }

    ranked["_risk_priority"] = (
        ranked["supplier_risk_level"]
        .map(risk_priority)
    )

    if ranked["_risk_priority"].isna().any():
        raise SupplierServiceError(
            "One or more supplier risk levels could not "
            "be ranked."
        )

    ranked = ranked.sort_values(
        by=[
            "_country_match",
            "supplier_risk_score",
            "_risk_priority",
            "average_lead_time_days",
            "on_time_delivery_rate",
            "cancellation_rate",
            "quality_issue_rate",
            "capacity_utilization",
            "supplier_id",
        ],
        ascending=[
            False,
            True,
            True,
            True,
            False,
            True,
            True,
            True,
            True,
        ],
        kind="stable",
    )

    return ranked


def find_alternative_supplier(
    category: str,
    destination_country: str,
    required_quantity: int,
    limit: int = 3,
) -> SupplierRecommendation:
    """
    Find and rank synthetic alternative suppliers.

    The supplier dataset does not contain available capacity measured
    in product units. The requested quantity is retained as context,
    but quantity feasibility cannot be verified automatically.
    """
    normalized_category = normalize_text(
        category
    )

    if not normalized_category:
        raise ValueError(
            "The product category cannot be empty."
        )

    normalized_destination = normalize_text(
        destination_country
    )

    if not normalized_destination:
        raise ValueError(
            "The destination country cannot be empty."
        )

    if required_quantity < 1:
        raise ValueError(
            "Required quantity must be at least 1."
        )

    if limit < 1:
        raise ValueError(
            "Supplier result limit must be at least 1."
        )

    if limit > 20:
        raise ValueError(
            "Supplier result limit cannot exceed 20."
        )

    compatible_categories = (
        get_compatible_supplier_categories(
            category
        )
    )

    dataframe = load_supplier_data()

    candidates = dataframe.loc[
        dataframe["_normalized_category"].isin(
            compatible_categories
        )
    ].copy()

    if candidates.empty:
        checked_categories = ", ".join(
            sorted(
                compatible_categories
            )
        )

        raise SupplierNotFoundError(
            "No synthetic supplier candidate was found for "
            f"shipment category '{category}'. "
            "Compatible supplier categories checked: "
            f"{checked_categories}."
        )

    ranked_candidates = rank_supplier_candidates(
        dataframe=candidates,
        destination_country=destination_country,
    )

    selected_candidates = (
        ranked_candidates
        .head(limit)
    )

    alternatives = [
        row_to_supplier_candidate(row)
        for _, row in selected_candidates.iterrows()
    ]

    recommended_supplier = next(
        (
            supplier
            for supplier in alternatives
            if supplier.supplier_risk_level
            in {
                RiskLevel.LOW,
                RiskLevel.MEDIUM,
            }
        ),
        None,
    )

    country_match_found = bool(
        selected_candidates[
            "_country_match"
        ].any()
    )

    compatible_category_text = ", ".join(
        sorted(
            compatible_categories
        )
    )

    limitation_parts = [
        "Supplier records are synthetic demonstration data.",
        (
            f"Shipment category '{category}' was matched against "
            f"the compatible supplier taxonomy: "
            f"{compatible_category_text}."
        ),
        (
            "The dataset does not contain available-capacity units, "
            "commercial terms, contractual availability, or live "
            "supplier status."
        ),
    ]

    if country_match_found:
        limitation_parts.append(
            "At least one selected candidate country matches "
            "the shipment destination."
        )
    else:
        limitation_parts.append(
            "No selected candidate country matches the shipment "
            "destination, so geographic suitability requires "
            "additional review."
        )

    if recommended_supplier is None:
        limitation_parts.append(
            "All returned candidates are classified as HIGH risk. "
            "No supplier is automatically recommended."
        )

    limitation_parts.append(
        "The requested quantity is recorded but cannot be "
        "validated against supplier capacity. Human approval "
        "is required before changing suppliers."
    )

    return SupplierRecommendation(
        category=category,
        destination_country=destination_country,
        required_quantity=required_quantity,
        recommended_supplier=recommended_supplier,
        alternatives=alternatives,
        candidate_count=int(
            len(candidates)
        ),
        data_source="SYNTHETIC_MVP",
        quantity_capacity_verified=False,
        limitation=" ".join(
            limitation_parts
        ),
    )


def clear_supplier_cache() -> None:
    """
    Clear cached supplier data for tests or dataset replacement.
    """
    load_supplier_data.cache_clear()