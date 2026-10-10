from pathlib import Path

from langchain_chroma import Chroma
from langchain_community.document_loaders import (
    Docx2txtLoader,
    PyPDFLoader,
    TextLoader,
)
from langchain_openai import AzureOpenAIEmbeddings
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
)

from rag.config import (
    COLLECTION_NAME,
    DOCUMENTS_DIRECTORY,
    VECTOR_STORE_DIRECTORY,
    get_azure_embedding_settings,
)


LOADER_MAPPING = {
    ".md": TextLoader,
    ".txt": TextLoader,
    ".pdf": PyPDFLoader,
    ".docx": Docx2txtLoader,
}


def load_documents() -> list:
    """
    Load supported narrative documents from the RAG document folder.
    """
    if not DOCUMENTS_DIRECTORY.exists():
        raise FileNotFoundError(
            "The RAG documents directory does not exist: "
            f"{DOCUMENTS_DIRECTORY}"
        )

    documents = []

    for file_path in sorted(
        DOCUMENTS_DIRECTORY.rglob("*")
    ):
        if not file_path.is_file():
            continue

        if file_path.name.startswith("."):
            continue

        file_extension = file_path.suffix.lower()

        if file_extension not in LOADER_MAPPING:
            print(
                f"Skipping {file_path.name}: "
                "unsupported narrative format."
            )
            continue

        print(f"Loading {file_path.name}...")

        loader_class = LOADER_MAPPING[file_extension]

        if file_extension in {".md", ".txt"}:
            loader = loader_class(
                str(file_path),
                encoding="utf-8",
            )
        else:
            loader = loader_class(str(file_path))

        loaded_documents = loader.load()

        for document in loaded_documents:
            document.metadata["source"] = file_path.name
            document.metadata["source_path"] = str(
                file_path.relative_to(
                    DOCUMENTS_DIRECTORY
                )
            )

        documents.extend(loaded_documents)

    return documents


def create_embeddings() -> AzureOpenAIEmbeddings:
    """
    Create the Azure OpenAI embedding client.
    """
    embedding_settings = (
        get_azure_embedding_settings()
    )

    return AzureOpenAIEmbeddings(
        **embedding_settings,
    )


def ingest_documents() -> dict:
    """
    Load operational documents, split them into chunks, generate
    embeddings, and save them to the persistent Chroma collection.
    """
    print(
        "Scanning RAG documents directory: "
        f"{DOCUMENTS_DIRECTORY}"
    )

    documents = load_documents()

    if not documents:
        raise RuntimeError(
            "No supported RAG documents were found. Add .md, .txt, "
            ".pdf, or .docx files to the documents directory."
        )

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        add_start_index=True,
    )

    chunks = text_splitter.split_documents(
        documents
    )

    if not chunks:
        raise RuntimeError(
            "The documents were loaded, but no text chunks "
            "were produced."
        )

    print(
        f"Loaded {len(documents)} documents and created "
        f"{len(chunks)} chunks."
    )

    embeddings = create_embeddings()

    VECTOR_STORE_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print(
        "Generating embeddings and saving to: "
        f"{VECTOR_STORE_DIRECTORY}"
    )

    vector_store = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=str(
            VECTOR_STORE_DIRECTORY
        ),
        collection_name=COLLECTION_NAME,
        collection_metadata={
            "description": (
                "Synthetic operational knowledge for the "
                "Supply-Chain Disruption Agent MVP"
            )
        },
    )

    result = {
        "documents_loaded": len(documents),
        "chunks_created": len(chunks),
        "collection_name": COLLECTION_NAME,
        "vector_store_path": str(
            VECTOR_STORE_DIRECTORY
        ),
        "stored_chunks": (
            vector_store._collection.count()
        ),
    }

    print("RAG ingestion completed successfully.")

    for key, value in result.items():
        print(f"{key}: {value}")

    return result


if __name__ == "__main__":
    ingest_documents()