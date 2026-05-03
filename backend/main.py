"""
main.py
FastAPI application — entry point for the RAG Assistant backend.

Endpoints:
    POST /upload             Upload & index a document
    POST /query              Ask a question via RAG
    GET  /documents          List indexed documents
    DELETE /documents/{id}   Remove a document
    GET  /health             Health / readiness check
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, List

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from document_processor import parse_document
from rag import embed_texts, run_rag
from vector_store import vector_store

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="RAG Assistant API",
    description="Retrieval-Augmented Generation backend powered by ChromaDB + OpenAI",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the frontend from /app (optional convenience)
_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(_frontend_dir):
    app.mount("/app", StaticFiles(directory=_frontend_dir, html=True), name="frontend")

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]]


class UploadResponse(BaseModel):
    status: str
    doc_id: str
    filename: str
    chunks: int


class DocumentInfo(BaseModel):
    doc_id: str
    filename: str
    chunk_count: int


class DeleteResponse(BaseModel):
    status: str
    doc_id: str
    chunks_deleted: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/test-openai", tags=["system"])
async def test_openai() -> Dict[str, Any]:
    """Diagnostic: verify OpenAI connectivity from this environment."""
    import traceback
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return {"status": "error", "detail": "OPENAI_API_KEY not set"}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        client.embeddings.create(model="text-embedding-3-small", input="ping")
        return {"status": "ok", "key_prefix": api_key[:8] + "..."}
    except Exception as exc:
        return {
            "status": "error",
            "exception_type": type(exc).__name__,
            "detail": str(exc),
            "traceback": traceback.format_exc(),
            "key_prefix": api_key[:8] + "...",
        }


@app.get("/health", tags=["system"])
async def health_check() -> Dict[str, Any]:
    """Basic readiness probe."""
    try:
        doc_count = vector_store.document_count()
        chunk_count = vector_store.chunk_count()
        return {
            "status": "ok",
            "documents": doc_count,
            "chunks": chunk_count,
            "collection": "rag_documents",
        }
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Health check failed: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "error", "detail": str(exc)},
        )


@app.post("/upload", response_model=UploadResponse, tags=["documents"])
async def upload_document(file: UploadFile = File(...)) -> UploadResponse:
    """
    Accept a PDF, TXT, or DOCX file, parse it into chunks, embed each chunk,
    and persist them in ChromaDB.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename provided.",
        )

    allowed_extensions = {".pdf", ".txt", ".docx"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(allowed_extensions))}",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    # Parse into text chunks
    try:
        chunks = parse_document(file_bytes, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not extract any text from the uploaded file.",
        )

    # Generate stable doc ID
    doc_id = str(uuid.uuid4())

    # Embed all chunks (single batched API call)
    try:
        embeddings = embed_texts(chunks)
    except (EnvironmentError, RuntimeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Embedding service error: {exc}",
        ) from exc

    # Store in ChromaDB
    try:
        vector_store.add_documents(
            doc_id=doc_id,
            chunks=chunks,
            embeddings=embeddings,
            metadata={"filename": file.filename},
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("ChromaDB storage error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Storage error: {exc}",
        ) from exc

    logger.info("Uploaded '%s' → doc_id=%s, %d chunks", file.filename, doc_id, len(chunks))

    return UploadResponse(
        status="ok",
        doc_id=doc_id,
        filename=file.filename,
        chunks=len(chunks),
    )


@app.post("/query", response_model=QueryResponse, tags=["rag"])
async def query(body: QueryRequest) -> QueryResponse:
    """
    Run the full RAG pipeline for a natural language question.
    """
    if not body.question or not body.question.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="'question' field must be a non-empty string.",
        )

    try:
        result = run_rag(body.question)
    except EnvironmentError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("RAG pipeline error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal error: {exc}",
        ) from exc

    return QueryResponse(answer=result["answer"], sources=result["sources"])


@app.get("/documents", response_model=List[DocumentInfo], tags=["documents"])
async def list_documents() -> List[DocumentInfo]:
    """Return metadata for all indexed documents."""
    try:
        docs = vector_store.list_documents()
        return [DocumentInfo(**d) for d in docs]
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("list_documents error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@app.delete("/documents/{doc_id}", response_model=DeleteResponse, tags=["documents"])
async def delete_document(doc_id: str) -> DeleteResponse:
    """Remove all chunks for a document from the vector store."""
    try:
        deleted = vector_store.delete_document(doc_id)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("delete_document error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    if deleted == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{doc_id}' not found in the vector store.",
        )

    logger.info("Deleted doc_id=%s (%d chunks)", doc_id, deleted)
    return DeleteResponse(status="ok", doc_id=doc_id, chunks_deleted=deleted)


# ---------------------------------------------------------------------------
# Dev entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
