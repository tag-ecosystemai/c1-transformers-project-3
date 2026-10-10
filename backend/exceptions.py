class BackendServiceError(RuntimeError):
    """Base exception for backend service failures."""


class ModelArtifactError(BackendServiceError):
    """Raised when a required model artifact cannot be loaded."""


class ModelFeatureError(BackendServiceError):
    """Raised when model input features are missing or invalid."""


class ModelInferenceError(BackendServiceError):
    """Raised when model inference fails."""


class ThresholdConfigurationError(BackendServiceError):
    """Raised when the configured decision threshold is invalid."""


class WeatherServiceError(BackendServiceError):
    """Raised when weather evidence cannot be retrieved or understood."""


class InvestigationNotRequiredError(ValueError):
    """
    Raised when the risk gate rejects a shipment that does not need
    investigation.

    A ValueError so existing callers that treat the rejection as a bad
    request keep working; the dedicated type lets callers tell it apart
    from other invalid input, such as a malformed shipment reference.
    """


class AzureOpenAIServiceError(BackendServiceError):
    """
    Raised when Azure OpenAI briefing generation cannot be completed.
    """


class InventoryServiceError(BackendServiceError):
    """
    Raised when inventory data cannot be loaded, validated or matched.
    """


class InventoryNotFoundError(InventoryServiceError):
    """Raised when no inventory record exists for a product."""
