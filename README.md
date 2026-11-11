# GapFinder AI

A Python hackathon MVP for diagnosing knowledge gaps from a student's own study material. FastAPI serves the API and a responsive, dependency-free web interface. Qdrant handles retrieval. Groq handles generation in live mode. Topic scores and study-time allocation are deterministic Python code.

## Run the local demo

Use Python 3.11–3.13 (3.12 recommended for embedding dependencies).

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
uvicorn gapfinder.main:app --host 127.0.0.1 --port 8000
```

Open [the app](http://127.0.0.1:8000) or [interactive API docs](http://127.0.0.1:8000/docs).

The demo account is `demo@gapfinder.local` / `study-better-2026`. It starts with a six-topic biology syllabus, notes, and past papers. You can also create a separate account and upload your own material. New accounts start empty. Data survives restarts in `./data`.

Demo mode needs no API key and makes no AI API calls. It uses Qdrant with lexical hash vectors, source-based fill-in-the-blank questions, and extractive source previews. This is an offline baseline, not semantic retrieval or an LLM demonstration. The interface labels it accordingly.

## Enable live RAG

```bash
pip install -e '.[semantic]'
```

Set these values in `.env`:

```dotenv
APP_MODE=live
GROQ_API_KEY=your-key-here
GROQ_MODEL=llama-3.3-70b-versatile
EMBEDDING_BACKEND=fastembed
EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
```

Restart the server. FastEmbed downloads its model on first use; Internet access is required for that download. Weights are cached under `data/models`. Choose a Groq model currently available to your account with JSON output support. Live mode does not silently fall back to offline generation after an API or validation failure. It does not create or expose the built-in demo credentials; create an account through the UI. Previously created accounts remain in the same database.

Notes, quiz evidence, and explanation requests are sent to Groq in live mode. Embeddings are generated locally. If `QDRANT_URL` points to a remote service, chunk text and source metadata are also stored there.

## What works

- Account creation, password hashing, HTTP-only login cookies, and saved student data.
- UTF-8 TXT/Markdown and text-based PDF ingestion, capped at 5 MB, 150 PDF pages, and 500,000 extracted characters.
- Additive syllabus topic maps (one topic per line, up to 30 topics).
- Paragraph-aware chunks with page, section, document, topic, and user metadata.
- Embedding-based topic assignment and Qdrant retrieval scoped to the authenticated user.
- Topic-balanced diagnostic MCQs, prioritized by current gaps. Only study notes provide quiz evidence; past papers without solutions are not used as answer evidence.
- Source references on every question. Live quiz citations are checked against retrieved chunk IDs, topic IDs, and verbatim supporting passages. This verifies provenance, not the pedagogical correctness of a generated question.
- Server-side answer keys and deterministic MCQ grading. Keys and explanations are returned only after submission. Finished attempts cannot be edited through resubmission.
- Per-topic accuracy using the last eight answers, evidence counts, and weak/medium/strong labels. Untested topics remain untested.
- Rolling daily revision plans that respect the exact minutes/day budget and update after quizzes.
- Overall and topic-level progress across attempts, with review of completed quizzes.
- Source-restricted explanations with numbered citations in live mode; source excerpts in demo mode.

## Retrieval and generation boundaries

Ingestion extracts text, chunks it, assigns topics using embedding similarity, and stores vectors plus metadata in Qdrant. These steps do not call Groq. For a diagnostic, application code selects topics and retrieves supporting study-note chunks. Groq receives only those chunks and returns question JSON. Pydantic and citation checks validate that JSON before the quiz is saved.

When the student submits answers, Python compares option indices against the saved answer key. It aggregates topic-level results and calculates the plan without asking an LLM to invent scores. For explanations, Qdrant retrieves relevant notes first; only then is Groq called with those excerpts. Uploads and excerpts are treated as untrusted content in the model prompts.

Priority is `gap × exam_weight`. The gap is `max(0.1, 1 - accuracy)` or `0.65` for an untested topic. Exam weight is `1 + 0.2 × min(matching_past_paper_chunks, 5)`. Time is assigned in blocks of up to 20 minutes, with diminishing weight for topics already allocated time. A day always totals the requested budget.

Past-paper relevance currently counts chunks assigned to each topic. It does not parse individual questions, marks, or historical exam frequency. Topic matching is automatic and should be reviewed on a real syllabus.

## Postgres and remote Qdrant

SQLite and embedded Qdrant keep the demo easy to run. SQLAlchemy and the Qdrant client also support the intended service stack. To start local services with Docker:

```bash
docker compose up -d
```

Then configure:

```dotenv
DATABASE_URL=postgresql+psycopg://gapfinder:gapfinder@localhost:5432/gapfinder
QDRANT_URL=http://localhost:6333
```

This creates a separate database; SQLite data is not automatically migrated. Each embedding backend/model combination uses a distinct Qdrant collection, and committed chunks are indexed at startup. Changing embedding configuration retains the old collection. Embedded Qdrant supports one app process: use a single Uvicorn worker locally. Use a Qdrant server for multiple workers, and run ingestion separately before scaling workers.

The Docker service passwords and unauthenticated Qdrant port are for loopback development only. Before deploying, use managed credentials, HTTPS, `COOKIE_SECURE=true`, database migrations/backups, durable storage, and an appropriate ingestion worker. The included app is a hackathon MVP, not a hardened public service.

## Tests

```bash
pytest -q
```

Tests use temporary SQLite/Qdrant storage and need neither API credentials nor embedding downloads. They check account isolation, source validation, hidden answer keys, immutable submissions, adaptive scoring, time budgets, upload errors, persistence, and mocked Groq output handling. A real Groq call requires your key. FastEmbed has a separate manual smoke check below:

```bash
python scripts/check_embeddings.py
```

## Project layout

- `gapfinder/main.py`: API, authentication, and application lifecycle.
- `gapfinder/ingestion.py`: extraction, chunking, and topic mapping.
- `gapfinder/retrieval.py`: hash/FastEmbed encoders and Qdrant.
- `gapfinder/generation.py`: Groq integration, offline questions, and provenance validation.
- `gapfinder/diagnosis.py`: scoring and bounded study schedules.
- `gapfinder/db.py`: SQLAlchemy models and password/session helpers.
- `gapfinder/static/`: browser interface.
- `gapfinder/samples/`: editable sample biology materials.

LangGraph is deliberately omitted: the current endpoints are explicit Python workflows. Introduce it if checkpointed execution or more complex branching becomes necessary.

## MVP boundaries

Assessment is multiple choice; open-ended answer grading, OCR, teacher analytics, curriculum prerequisite graphs, topic-map editing, password reset, and spaced-repetition reminders are not implemented. A single correct answer gives provisional evidence, not proof of mastery. The source assistant prompts the model to stay grounded, but citation presence alone does not guarantee every generated claim is supported.
