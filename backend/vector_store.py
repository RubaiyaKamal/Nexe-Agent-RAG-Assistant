"""
vector_store.py
ChromaDB wrapper for persistent document storage and similarity search.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import chromadb  # type: ignore
from chromadb.config import Settings  # type: ignore

logger = logging.getLogger(__name__)

COLLECTION_NAME = "rag_documents"
# Resolve chroma_db path relative to this file so it works regardless of CWD
_DB_PATH = os.path.join(os.path.dirname(__file__), "chroma_db")


class VectorStore:
    """Thin wrapper around a ChromaDB persistent collection."""

    def __init__(self, db_path: str = _DB_PATH, collection_name: str = COLLECTION_NAME):
        self._db_path = db_path
        self._collection_name = collection_name
        self._client: Optional[chromadb.PersistentClient] = None
        self._collection = None

    # ------------------------------------------------------------------
    # Lazy initialisation
    # ------------------------------------------------------------------

    def _get_collection(self):
        if self._collection is None:
            os.makedirs(self._db_path, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=self._db_path,
                settings=Settings(anonymized_telemetry=False),
            )
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                "ChromaDB collection '%s' ready at '%s'",
                self._collection_name,
                self._db_path,
            )
        return self._collection

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_documents(
        self,
        doc_id: str,
        chunks: List[str],
        embeddings: List[List[float]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Store *chunks* with their pre-computed *embeddings* under *doc_id*.

        Each chunk gets a unique ID: ``<doc_id>_chunk_<index>``.
        """
        if not chunks:
            logger.warning("add_documents called with empty chunks for doc_id='%s'", doc_id)
            return

        collection = self._get_collection()

        ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
        meta_list: List[Dict[str, Any]] = [
            {
                "doc_id": doc_id,
                "chunk_index": i,
                **(metadata or {}),
            }
            for i in range(len(chunks))
        ]

        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=meta_list,
        )
        logger.info("Stored %d chunks for doc_id='%s'", len(chunks), doc_id)

    def query(
        self,
        query_embedding: List[float],
        n_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Return the top-*n_results* most similar chunks as a list of dicts::

            [{"text": str, "doc_id": str, "chunk_index": int, "distance": float}, ...]
        """
        collection = self._get_collection()
        total = collection.count()
        if total == 0:
            return []

        # Cap n_results to avoid ChromaDB error when collection is smaller
        n_results = min(n_results, total)

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )

        output: List[Dict[str, Any]] = []
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for doc, meta, dist in zip(docs, metas, distances):
            output.append(
                {
                    "text": doc,
                    "doc_id": meta.get("doc_id", "unknown"),
                    "chunk_index": meta.get("chunk_index", -1),
                    "distance": round(dist, 6),
                    "filename": meta.get("filename", ""),
                }
            )

        return output

    def list_documents(self) -> List[Dict[str, Any]]:
        """
        Return a deduplicated list of stored documents with chunk counts::

            [{"doc_id": str, "filename": str, "chunk_count": int}, ...]
        """
        collection = self._get_collection()
        if collection.count() == 0:
            return []

        results = collection.get(include=["metadatas"])
        metas = results.get("metadatas", [])

        doc_map: Dict[str, Dict[str, Any]] = {}
        for meta in metas:
            doc_id = meta.get("doc_id", "unknown")
            if doc_id not in doc_map:
                doc_map[doc_id] = {
                    "doc_id": doc_id,
                    "filename": meta.get("filename", ""),
                    "chunk_count": 0,
                }
            doc_map[doc_id]["chunk_count"] += 1

        return list(doc_map.values())

    def delete_document(self, doc_id: str) -> int:
        """
        Delete all chunks belonging to *doc_id*.
        Returns the number of chunks removed.
        """
        collection = self._get_collection()

        # Fetch matching IDs
        results = collection.get(
            where={"doc_id": doc_id},
            include=[],
        )
        ids_to_delete = results.get("ids", [])

        if not ids_to_delete:
            logger.warning("delete_document: no chunks found for doc_id='%s'", doc_id)
            return 0

        collection.delete(ids=ids_to_delete)
        logger.info("Deleted %d chunks for doc_id='%s'", len(ids_to_delete), doc_id)
        return len(ids_to_delete)

    def document_count(self) -> int:
        """Total number of unique documents in the store."""
        return len(self.list_documents())

    def chunk_count(self) -> int:
        """Total number of chunks stored."""
        return self._get_collection().count()


# ---------------------------------------------------------------------------
# Module-level singleton (shared across the FastAPI app)
# ---------------------------------------------------------------------------
vector_store = VectorStore()
