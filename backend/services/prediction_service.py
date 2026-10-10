from pathlib import Path
from threading import Lock
from typing import Any

import joblib
import numpy as np
import pandas as pd

from backend.config import settings
from backend.exceptions import (
    ModelArtifactError,
    ModelFeatureError,
    ModelInferenceError,
    ThresholdConfigurationError,
)
from backend.models.schemas import (
    PredictionResponse,
    RiskLevel,
    ShipmentResponse,
)
from backend.services.model_feature_service import (
    get_model_feature_row,
)
from backend.services.shipment_service import (
    get_shipment_status,
)


# The model artifacts are loaded once per backend process.
#
# A simple lru_cache can allow more than one cold-start invocation when
# multiple requests arrive before the first invocation finishes. This lock
# ensures that only one request performs the expensive deserialization.
_model_artifacts: tuple[Any, Any] | None = None
_model_load_lock = Lock()


def _load_model_artifacts_from_disk() -> tuple[Any, Any]:
    """
    Deserialize and validate the fitted preprocessor and XGBoost model.

    This function performs the expensive disk-loading work. Callers
    should use load_model_artifacts() instead of calling this function
    directly.
    """
    preprocessor_path = Path(
        settings.preprocessor_path
    )

    model_path = Path(
        settings.model_path
    )

    missing_artifacts: list[str] = []

    if not preprocessor_path.exists():
        missing_artifacts.append(
            str(preprocessor_path)
        )

    if not model_path.exists():
        missing_artifacts.append(
            str(model_path)
        )

    if missing_artifacts:
        raise ModelArtifactError(
            "Required model artifacts were not found: "
            + ", ".join(missing_artifacts)
        )

    try:
        preprocessor = joblib.load(
            preprocessor_path
        )
    except Exception as exc:
        raise ModelArtifactError(
            "Unable to load the preprocessing artifact from "
            f"'{preprocessor_path}': {exc}"
        ) from exc

    try:
        model = joblib.load(
            model_path
        )
    except Exception as exc:
        raise ModelArtifactError(
            "Unable to load the XGBoost model from "
            f"'{model_path}': {exc}"
        ) from exc

    if not hasattr(
        preprocessor,
        "transform",
    ):
        raise ModelArtifactError(
            "The loaded preprocessor does not provide transform()."
        )

    if not hasattr(
        model,
        "predict_proba",
    ):
        raise ModelArtifactError(
            "The loaded model does not provide predict_proba()."
        )

    return preprocessor, model


def load_model_artifacts() -> tuple[Any, Any]:
    """
    Load and cache the fitted preprocessor and XGBoost model.

    Artifacts are loaded exactly once per backend process. The lock
    prevents concurrent cold-start requests from loading multiple model
    copies and exhausting available memory.
    """
    global _model_artifacts

    if _model_artifacts is not None:
        return _model_artifacts

    with _model_load_lock:
        if _model_artifacts is None:
            _model_artifacts = (
                _load_model_artifacts_from_disk()
            )

    return _model_artifacts


def get_expected_model_features(
    preprocessor: Any,
) -> list:
    """
    Return the raw input columns expected by the fitted preprocessor.
    """
    feature_names = getattr(
        preprocessor,
        "feature_names_in_",
        None,
    )

    if feature_names is None:
        raise ModelFeatureError(
            "The saved preprocessor does not expose "
            "feature_names_in_. The model input feature list "
            "must be supplied explicitly."
        )

    return [
        str(feature)
        for feature in feature_names
    ]


def prepare_model_features(
    shipment: ShipmentResponse,
    expected_features: list[str],
) -> pd.DataFrame:
    """
    Convert a Shipment Tool record into the raw DataFrame expected by
    the saved preprocessing pipeline.
    """
    shipment_values = shipment.model_dump()

    shipment_identifier = str(
        shipment.shipment_id
    )

    order_item_id = getattr(
        shipment,
        "order_item_id",
        None,
    )

    if order_item_id is None:
        order_item_id = (
            shipment_identifier.removeprefix(
                "SHP-"
            )
        )

    order_item_id = str(
        order_item_id
    ).strip()

    if not order_item_id:
        raise ModelFeatureError(
            "The order-item identifier could not be derived "
            f"for shipment '{shipment.shipment_id}'."
        )

    order_date = pd.to_datetime(
        shipment.order_date,
        errors="coerce",
    )

    if pd.isna(order_date):
        raise ModelFeatureError(
            "Invalid order date for shipment "
            f"'{shipment.shipment_id}'."
        )

    feature_values: dict[str, Any] = {
        # Normalized Shipment Tool fields
        "order_id": shipment.order_id,
        "order_item_id": order_item_id,
        "shipment_id": shipment.shipment_id,
        "product_name": shipment.product_name,
        "category": shipment.category,
        "department": shipment.department,
        "market": shipment.market,
        "customer_country": shipment.customer_country,
        "destination_country": (
            shipment.destination_country
        ),
        "destination_region": (
            shipment.destination_region
        ),
        "destination_state": (
            shipment.destination_state
        ),
        "destination_city": (
            shipment.destination_city
        ),
        "shipping_mode": shipment.shipping_mode,
        "scheduled_shipping_days": (
            shipment.scheduled_shipping_days
        ),
        "quantity": shipment.quantity,
        "product_price": shipment.product_price,
        "sales": shipment.sales,
        "discount": shipment.discount,
        "order_date": order_date,
        "latitude": shipment.latitude,
        "longitude": shipment.longitude,
        "historical_product_delay_rate": (
            shipment.historical_product_delay_rate
        ),
        "historical_market_delay_rate": (
            shipment.historical_market_delay_rate
        ),
        "historical_shipping_mode_delay_rate": (
            shipment
            .historical_shipping_mode_delay_rate
        ),

        # Possible original DataCo field names
        "Order Id": shipment.order_id,
        "Order Item Id": order_item_id,
        "Product Name": shipment.product_name,
        "Category Name": shipment.category,
        "Department Name": shipment.department,
        "Market": shipment.market,
        "Customer Country": (
            shipment.customer_country
        ),
        "Order Country": (
            shipment.destination_country
        ),
        "Order Region": (
            shipment.destination_region
        ),
        "Order State": (
            shipment.destination_state
        ),
        "Order City": (
            shipment.destination_city
        ),
        "Shipping Mode": shipment.shipping_mode,
        "Days for shipment (scheduled)": (
            shipment.scheduled_shipping_days
        ),
        "Order Item Quantity": shipment.quantity,
        "Product Price": shipment.product_price,
        "Sales": shipment.sales,
        "Order Item Discount": shipment.discount,
        "order date (DateOrders)": order_date,
        "Latitude": shipment.latitude,
        "Longitude": shipment.longitude,

        # Engineered date features
        "order_year": int(order_date.year),
        "order_month": int(order_date.month),
        "order_day": int(order_date.day),
        "order_dayofweek": int(
            order_date.dayofweek
        ),
        "order_hour": int(order_date.hour),
        "order_quarter": int(
            order_date.quarter
        ),
    }

    feature_values.update(
        shipment_values
    )

    missing_features = [
        feature
        for feature in expected_features
        if feature not in feature_values
    ]

    if missing_features:
        raise ModelFeatureError(
            "The Shipment Tool cannot supply all model inputs. "
            "Missing features: "
            + ", ".join(missing_features)
        )

    feature_row = {
        feature: feature_values[feature]
        for feature in expected_features
    }

    features = pd.DataFrame(
        [feature_row],
        columns=expected_features,
    )

    if features.empty:
        raise ModelFeatureError(
            "Model feature preparation produced an empty DataFrame."
        )

    return features


def classify_risk(
    probability: float,
    decision_threshold: float,
    high_risk_threshold: float,
) -> tuple[RiskLevel, bool]:
    """
    Classify shipment delay risk using the finalized operational rules.

    Rules:
        probability < decision_threshold:
            LOW risk, monitor only.

        decision_threshold <= probability < high_risk_threshold:
            MEDIUM risk, trigger investigation.

        probability >= high_risk_threshold:
            HIGH risk, trigger investigation.
    """
    if not 0 <= probability <= 1:
        raise ModelInferenceError(
            "The predicted probability must be between 0 and 1."
        )

    if not 0 < decision_threshold < 1:
        raise ThresholdConfigurationError(
            "RISK_THRESHOLD must be greater than 0 and less than 1."
        )

    if not 0 < high_risk_threshold <= 1:
        raise ThresholdConfigurationError(
            "HIGH_RISK_THRESHOLD must be greater than 0 "
            "and less than or equal to 1."
        )

    if high_risk_threshold <= decision_threshold:
        raise ThresholdConfigurationError(
            "HIGH_RISK_THRESHOLD must be greater than "
            "RISK_THRESHOLD."
        )

    if probability < decision_threshold:
        return RiskLevel.LOW, False

    if probability < high_risk_threshold:
        return RiskLevel.MEDIUM, True

    return RiskLevel.HIGH, True


def predict_probability(
    shipment: ShipmentResponse,
) -> float:
    """
    Run the saved preprocessing and XGBoost inference pipeline.
    """
    preprocessor, model = load_model_artifacts()

    expected_features = get_expected_model_features(
        preprocessor
    )

    raw_features = get_model_feature_row(
        shipment_id=(
            getattr(
                shipment,
                "shipment_reference",
                None,
            )
            or (
                shipment.shipment_id
                if str(
                    shipment.shipment_id
                ).startswith("SHP-")
                else (
                    f"SHP-{shipment.shipment_id}"
                )
            )
        ),
        expected_features=expected_features,
    )

    try:
        transformed_features = (
            preprocessor.transform(
                raw_features
            )
        )
    except Exception as exc:
        raise ModelInferenceError(
            "Feature preprocessing failed for shipment "
            f"'{shipment.shipment_id}': {exc}"
        ) from exc

    if transformed_features.shape[0] != 1:
        raise ModelFeatureError(
            "The preprocessor did not return exactly one row."
        )

    transformed_feature_count = (
        transformed_features.shape[1]
    )

    model_feature_count = getattr(
        model,
        "n_features_in_",
        None,
    )

    if (
        model_feature_count is not None
        and transformed_feature_count
        != model_feature_count
    ):
        raise ModelFeatureError(
            "Transformed feature count does not match the model. "
            f"Preprocessor produced {transformed_feature_count}; "
            f"model expects {model_feature_count}."
        )

    try:
        probabilities = model.predict_proba(
            transformed_features
        )
    except Exception as exc:
        raise ModelInferenceError(
            "XGBoost inference failed for shipment "
            f"'{shipment.shipment_id}': {exc}"
        ) from exc

    probabilities = np.asarray(
        probabilities
    )

    if probabilities.ndim != 2:
        raise ModelInferenceError(
            "The model returned an unexpected probability shape: "
            f"{probabilities.shape}."
        )

    if probabilities.shape[0] != 1:
        raise ModelInferenceError(
            "The model did not return exactly one prediction."
        )

    if probabilities.shape[1] < 2:
        raise ModelInferenceError(
            "The classifier did not return a positive-class "
            "probability."
        )

    probability = float(
        probabilities[0, 1]
    )

    if not np.isfinite(
        probability
    ):
        raise ModelInferenceError(
            "The model returned a non-finite probability."
        )

    if not 0 <= probability <= 1:
        raise ModelInferenceError(
            "The model returned a probability outside 0 to 1."
        )

    return probability


def predict_delay_risk(
    shipment_id: str,
) -> PredictionResponse:
    """
    Retrieve a shipment, run real model inference, and apply the
    configured risk gate.
    """
    shipment = get_shipment_status(
        shipment_id
    )

    if settings.mock_mode:
        raise ModelInferenceError(
            "MOCK_MODE is enabled. Disable MOCK_MODE to use "
            "the saved model artifacts."
        )

    probability = predict_probability(
        shipment
    )

    (
        risk_level,
        requires_investigation,
    ) = classify_risk(
        probability=probability,
        decision_threshold=(
            settings.risk_threshold
        ),
        high_risk_threshold=(
            settings.high_risk_threshold
        ),
    )

    public_shipment_id = getattr(
        shipment,
        "shipment_reference",
        None,
    )

    if not public_shipment_id:
        raw_shipment_id = str(
            shipment.shipment_id
        ).strip()

        if raw_shipment_id.upper().startswith(
            "SHP-"
        ):
            public_shipment_id = (
                raw_shipment_id.upper()
            )
        else:
            public_shipment_id = (
                f"SHP-{raw_shipment_id}"
            )

    public_shipment_id = str(
        public_shipment_id
    ).strip().upper()

    return PredictionResponse(
        shipment_id=public_shipment_id,
        delay_probability=round(
            probability,
            4,
        ),
        risk_level=risk_level,
        requires_investigation=(
            requires_investigation
        ),
    )


def clear_model_cache() -> None:
    """
    Clear cached model artifacts for testing or model replacement.

    The same model-loading lock is used so the cache cannot be cleared
    while another request is loading model artifacts.
    """
    global _model_artifacts

    with _model_load_lock:
        _model_artifacts = None