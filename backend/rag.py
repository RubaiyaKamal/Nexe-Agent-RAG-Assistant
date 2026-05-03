"""
rag.py
RAG pipeline: embed queries, retrieve context, generate answers with GPT.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from dotenv import load_dotenv
from openai import OpenAI, APIError

from vector_store import vector_store

load_dotenv()

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
CHAT_MODEL = "gpt-4o-mini"
TOP_K = 5  # number of context chunks to retrieve

SYSTEM_PROMPT = (
    "You are a helpful assistant. Answer the user's question based solely on "
    "the provided context excerpts. If the answer is not present in the context, "
    "clearly state that you don't have enough information to answer. "
    "Be concise and accurate."
)


def _get_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY environment variable is not set. "
            "Create a .env file with OPENAI_API_KEY=<your-key>."
        )
    return OpenAI(api_key=api_key)


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def embed_text(text: str) -> List[float]:
    """
    Return an embedding vector for *text* using OpenAI text-embedding-3-small.

    Raises:
        EnvironmentError: if OPENAI_API_KEY is missing.
        RuntimeError: on API failure.
    """
    client = _get_client()
    try:
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text,
        )
        return response.data[0].embedding
    except APIError as exc:
        logger.error("OpenAI embedding API error: %s", exc)
        raise RuntimeError(f"Embedding API error: {exc}") from exc


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Embed multiple texts in a single API call (more efficient than looping).

    Raises:
        EnvironmentError: if OPENAI_API_KEY is missing.
        RuntimeError: on API failure.
    """
    if not texts:
        return []

    client = _get_client()
    try:
        response = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=texts,
        )
        # Response items are ordered by index
        ordered = sorted(response.data, key=lambda d: d.index)
        return [item.embedding for item in ordered]
    except Exception as exc:
        logger.error("OpenAI batch embedding error [%s]: %s", type(exc).__name__, exc, exc_info=True)
        raise RuntimeError(f"Embedding API error [{type(exc).__name__}]: {exc}") from exc


# ---------------------------------------------------------------------------
# Answer generation
# ---------------------------------------------------------------------------

def answer_question(question: str, context_chunks: List[str]) -> str:
    """
    Generate an answer for *question* grounded in *context_chunks*.

    Raises:
        EnvironmentError: if OPENAI_API_KEY is missing.
        RuntimeError: on API failure.
    """
    client = _get_client()

    if context_chunks:
        numbered = "\n\n".join(
            f"[{i + 1}] {chunk}" for i, chunk in enumerate(context_chunks)
        )
        user_message = (
            f"Context:\n{numbered}\n\n"
            f"Question: {question}"
        )
    else:
        user_message = (
            "No relevant context was found in the document store.\n\n"
            f"Question: {question}"
        )

    try:
        response = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
            max_tokens=1024,
        )
        return response.choices[0].message.content or ""
    except APIError as exc:
        logger.error("OpenAI chat API error: %s", exc)
        raise RuntimeError(f"Chat API error: {exc}") from exc


# ---------------------------------------------------------------------------
# Full RAG pipeline
# ---------------------------------------------------------------------------

def run_rag(question: str) -> Dict[str, Any]:
    """
    End-to-end RAG pipeline:
    1. Embed the question.
    2. Retrieve top-K relevant chunks from ChromaDB.
    3. Generate an answer with GPT using those chunks as context.

    Returns::

        {
            "answer": str,
            "sources": [{"doc_id": str, "filename": str, "chunk_index": int,
                         "distance": float, "text": str}, ...]
        }
    """
    if not question or not question.strip():
        return {"answer": "Please provide a non-empty question.", "sources": []}

    # 1. Embed
    query_embedding = embed_text(question)

    # 2. Retrieve
    retrieved = vector_store.query(query_embedding, n_results=TOP_K)

    # 3. Answer
    context_texts = [item["text"] for item in retrieved]
    answer = answer_question(question, context_texts)

    return {
        "answer": answer,
        "sources": retrieved,
    }
