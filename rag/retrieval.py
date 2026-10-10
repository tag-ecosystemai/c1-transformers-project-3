from pathlib import Path
from typing import Any

from langchain_chroma import Chroma
from langchain_openai import AzureOpenAIEmbeddings

from rag.config import (
    COLLECTION_NAME,
    VECTOR_STORE_DIRECTORY,
    get_azure_embedding_settings,
)


class RAGRetrievalError(RuntimeError):
    """
    Raised when operational knowledge cannot be retrieved.
    """


def create_embeddings() -> AzureOpenAIEmbeddings:
    """
    Create the same embedding client used during ingestion.
    """
    embedding_settings = (
        get_azure_embedding_settings()
    )

    return AzureOpenAIEmbeddings(
        **embedding_settings,
    )


def load_vector_store() -> Chroma:
    """
    Load the persistent Chroma collection used by ingestion.
    """
    if not VECTOR_STORE_DIRECTORY.exists():
        raise RAGRetrievalError(
            "The RAG vector store does not exist at "
            f"'{VECTOR_STORE_DIRECTORY}'. "
            "Run the ingestion process first."
        )

    embeddings = create_embeddings()

    try:
        vector_store = Chroma(
            persist_directory=str(
                VECTOR_STORE_DIRECTORY
            ),
            embedding_function=embeddings,
            collection_name=COLLECTION_NAME,
        )
    except Exception as exc:
        raise RAGRetrievalError(
            "Unable to load the RAG vector store: "
            f"{exc}"
        ) from exc

    stored_chunks = (
        vector_store._collection.count()
    )

    if stored_chunks == 0:
        raise RAGRetrievalError(
            "The RAG collection exists but contains no chunks. "
            "Run the ingestion process first."
        )

    return vector_store


def retrieve_operational_knowledge(
    query: str,
    k: int = 3,
) -> list[dict[str, Any]]:
    """
    Retrieve operational knowledge using semantic similarity.

    Returns structured chunks containing content, source information,
    metadata, and a relevance score.
    """
    normalized_query = query.strip()

    if not normalized_query:
        raise ValueError(
            "The RAG retrieval query cannot be empty."
        )

    if k < 1:
        raise ValueError(
            "The number of retrieval results must be at least 1."
        )

    vector_store = load_vector_store()

    try:
        results = (
            vector_store
            .similarity_search_with_relevance_scores(
                normalized_query,
                k=k,
            )
        )
    except Exception as exc:
        raise RAGRetrievalError(
            "Operational knowledge retrieval failed: "
            f"{exc}"
        ) from exc

    structured_results = []

    for rank, result in enumerate(
        results,
        start=1,
    ):
        document, relevance_score = result

        source = document.metadata.get(
            "source",
            "Unknown source",
        )

        source_path = document.metadata.get(
            "source_path",
            source,
        )

        structured_results.append(
            {
                "rank": rank,
                "content": document.page_content,
                "source": source,
                "source_path": source_path,
                "relevance_score": float(
                    relevance_score
                ),
                "metadata": dict(
                    document.metadata
                ),
            }
        )

    return structured_results


if __name__ == "__main__":
    test_query = (
        "What should operations do when a shipment has a high "
        "risk of delay?"
    )

    answers = retrieve_operational_knowledge(
        test_query,
        k=3,
    )

    print("\n=== RETRIEVED KNOWLEDGE ===\n")

    for answer in answers:
        print(
            f"--- Result {answer['rank']} ---"
        )
        print(
            f"Source: {answer['source']}"
        )
        print(
            "Relevance: "
            f"{answer['relevance_score']:.4f}"
        )
        print(answer["content"])
        print()