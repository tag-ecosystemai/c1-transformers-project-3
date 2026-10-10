from pathlib import Path

from rag.retrieval import (
    retrieve_operational_knowledge,
)

import pytest


pytestmark = pytest.mark.integration


def test_rag_retrieves_real_pdf_sources():
    results = retrieve_operational_knowledge(
        query=(
            "What should operations do for a "
            "medium-risk shipment with elevated "
            "historical delay rates?"
        ),
        k=5,
    )

    assert results

    available_documents = {
        path.name
        for path in Path(
            "rag/documents"
        ).glob("*.pdf")
    }

    retrieved_sources = {
        result["source"]
        for result in results
    }

    assert retrieved_sources
    assert retrieved_sources.issubset(
        available_documents
    )


def test_rag_returns_structured_metadata():
    results = retrieve_operational_knowledge(
        query=(
            "When should shipment rerouting "
            "be considered?"
        ),
        k=3,
    )

    assert results

    for result in results:
        assert "rank" in result
        assert "content" in result
        assert "source" in result
        assert "source_path" in result
        assert "relevance_score" in result
        assert "metadata" in result