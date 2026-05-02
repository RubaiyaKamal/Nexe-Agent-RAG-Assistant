# RAG Assistant

A production-quality Retrieval-Augmented Generation (RAG) assistant.  
Upload PDF, TXT, or DOCX files; ask questions; get answers grounded in your documents.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | Python · FastAPI |
| Vector Store | ChromaDB (persistent, local) |
| Embeddings | OpenAI `text-embedding-3-small` |
| LLM | OpenAI `gpt-4o-mini` |
| Frontend | Vanilla HTML / CSS / JS (no framework) |
| File parsing | pypdf · python-docx |

## Project Layout

```
Nexe-Agent-RAG-Assistant/
├── backend/
│   ├── main.py               FastAPI app + all endpoints
│   ├── rag.py                RAG pipeline (embed → retrieve → answer)
│   ├── document_processor.py Parse PDF / TXT / DOCX → chunks
│   ├── vector_store.py       ChromaDB wrapper
│   └── requirements.txt
├── frontend/
│   ├── index.html            Single-page UI
│   ├── style.css             Dark-theme stylesheet
│   └── app.js                Frontend logic
├── .env.example
├── .gitignore
└── README.md
```

## Quick Start

### 1. Prerequisites

- Python 3.10+
- An OpenAI API key

### 2. Clone & configure

```bash
git clone <repo-url>
cd Nexe-Agent-RAG-Assistant

cp .env.example .env
# Edit .env and set OPENAI_API_KEY=sk-...
```

### 3. Install dependencies

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 4. Run the backend

```bash
# From the backend/ directory (with venv active)
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API is now live at **http://localhost:8000**.  
Interactive docs: **http://localhost:8000/docs**

### 5. Open the frontend

Open `frontend/index.html` in your browser **or** visit:

```
http://localhost:8000/app
```

(The backend also serves the frontend at `/app` via `StaticFiles`.)

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health + stats |
| `POST` | `/upload` | Upload & index a document |
| `POST` | `/query` | Ask a question (RAG) |
| `GET` | `/documents` | List indexed documents |
| `DELETE` | `/documents/{doc_id}` | Remove a document |

### POST /upload

```
Content-Type: multipart/form-data
Body: file=<PDF|TXT|DOCX>
```

Response:
```json
{"status": "ok", "doc_id": "uuid", "filename": "report.pdf", "chunks": 42}
```

### POST /query

```json
{"question": "What is the main topic of the uploaded document?"}
```

Response:
```json
{
  "answer": "The document covers…",
  "sources": [
    {"text": "…excerpt…", "doc_id": "uuid", "filename": "report.pdf",
     "chunk_index": 3, "distance": 0.12}
  ]
}
```

## Configuration

All settings live in `.env`:

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI secret key |

## How It Works

1. **Upload** — File is parsed into overlapping text chunks (~500 tokens, 50 overlap).
2. **Embed** — All chunks are embedded in a single batched call to `text-embedding-3-small`.
3. **Store** — Embeddings + metadata are persisted in a local ChromaDB collection.
4. **Query** — The question is embedded, top-5 chunks are retrieved by cosine similarity.
5. **Answer** — GPT-4o-mini receives the question + context and generates a grounded response.

## License

MIT
