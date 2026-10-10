from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Central configuration for the backend application."""

    # ========================================================
    # APPLICATION
    # ========================================================

    app_name: str = "Supply-Chain Disruption Agent API"
    app_environment: str = "development"
    debug: bool = False
    mock_mode: bool = False

    # ========================================================
    # BACKEND
    # ========================================================

    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    backend_url: str = "http://localhost:8000"

    # ========================================================
    # FRONTEND
    # ========================================================

    frontend_url: str = (
        "http://localhost:3000,"
        "http://localhost:5173"
    )

    # ========================================================
    # SHIPMENT TOOL
    # ========================================================

    shipment_data_path: Path = (
        PROJECT_ROOT
        / "data"
        / "processed"
        / "shipment_tool_data.csv"
    )

    # ========================================================
    # MACHINE LEARNING
    # ========================================================

    model_data_path: Path = (
        PROJECT_ROOT
        / "data"
        / "processed"
        / "df_model.zip"
    )

    model_path: Path = (
        PROJECT_ROOT
        / "models"
        / "xgb_model.joblib"
    )

    preprocessor_path: Path = (
        PROJECT_ROOT
        / "models"
        / "preprocessor.joblib"
    )

    risk_threshold: float = 0.40
    high_risk_threshold: float = 0.70

    # ========================================================
    # WEATHER TOOL
    # ========================================================

    weather_api_base_url: str = (
        "https://archive-api.open-meteo.com/v1/archive"
    )

    weather_geocoding_url: str = (
        "https://geocoding-api.open-meteo.com/v1/search"
    )

    weather_timeout_seconds: float = 10.0
    weather_api_key: str | None = None

    # ========================================================
    # RAG
    # ========================================================

    rag_documents_path: Path = (
        PROJECT_ROOT
        / "rag"
        / "documents"
    )

    vector_store_path: Path = (
        PROJECT_ROOT
        / "rag"
        / "vector_store"
    )

    rag_collection_name: str = "operational_sops"

    rag_chunk_size: int = 1000
    rag_chunk_overlap: int = 200
    rag_top_k: int = 5

    # ========================================================
    # AZURE OPENAI
    # ========================================================

    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_api_version: str = "2024-02-01"

    azure_openai_chat_deployment: str | None = None
    azure_openai_embedding_deployment: str | None = None

    # Temporary compatibility with Joy's previous RAG code.
    azure_openai_deployment_name: str | None = None

    # ========================================================
    # SUPPLIER TOOL
    # ========================================================

    supplier_data_path: Path = (
        PROJECT_ROOT
        / "data"
        / "processed"
        / "supplier_tool_data.csv"
    )

    # ========================================================
    # INVENTORY TOOL
    # ========================================================

    inventory_data_path: Path = (
        PROJECT_ROOT
        / "data"
        / "processed"
        / "inventory_tool_data.csv"
    )

    # ========================================================
    # PYDANTIC SETTINGS
    # ========================================================

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Create and cache one settings object per backend process."""
    return Settings()


settings = get_settings()