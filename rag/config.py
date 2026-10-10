import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DOCUMENTS_DIRECTORY = (
    PROJECT_ROOT
    / "rag"
    / "documents"
)


def resolve_project_path(
    environment_variable: str,
    default_relative_path: str,
) -> Path:
    """
    Resolve a path from an environment variable.

    Absolute paths are used directly. Relative paths are resolved
    against the repository root.
    """
    configured_path = os.getenv(
        environment_variable,
        default_relative_path,
    )

    path = Path(configured_path).expanduser()

    if not path.is_absolute():
        path = PROJECT_ROOT / path

    return path.resolve()


VECTOR_STORE_DIRECTORY = resolve_project_path(
    environment_variable="VECTOR_STORE_PATH",
    default_relative_path="rag/vector_store",
)

COLLECTION_NAME = os.getenv(
    "RAG_COLLECTION_NAME",
    "operational_sops",
)


def get_azure_embedding_settings() -> dict[str, str]:
    """
    Read and validate the Azure OpenAI embedding configuration.
    """
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")

    api_version = os.getenv(
        "AZURE_OPENAI_API_VERSION",
        "2024-02-01",
    )

    deployment = (
        os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
        or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
    )

    missing_settings = []

    if not endpoint:
        missing_settings.append("AZURE_OPENAI_ENDPOINT")

    if not api_key:
        missing_settings.append("AZURE_OPENAI_API_KEY")

    if not deployment:
        missing_settings.append(
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
        )

    if missing_settings:
        raise RuntimeError(
            "Missing Azure embedding configuration: "
            + ", ".join(missing_settings)
        )

    return {
        "azure_endpoint": endpoint,
        "api_key": api_key,
        "openai_api_version": api_version,
        "azure_deployment": deployment,
    }