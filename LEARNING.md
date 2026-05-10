# Project Learnings — Lumen Medical Report Simplifier

This document captures every concept, technology, and lesson learned while building the Lumen project from scratch. Topics are explained simply first, then in more technical depth where the implementation was genuinely complex. Bug fixes are documented in a structured format at the end.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [FastAPI — The Backend Framework](#2-fastapi--the-backend-framework)
3. [Async Programming in Python](#3-async-programming-in-python)
4. [PostgreSQL and SQLAlchemy](#4-postgresql-and-sqlalchemy)
5. [Alembic — Database Migrations](#5-alembic--database-migrations)
6. [Redis — Queue and Cache](#6-redis--queue-and-cache)
7. [The Worker Pipeline](#7-the-worker-pipeline)
8. [OCR — Multi-Tier Text Extraction](#8-ocr--multi-tier-text-extraction)
9. [LLM Integration and Prompt Engineering](#9-llm-integration-and-prompt-engineering)
10. [RAG — Retrieval-Augmented Generation](#10-rag--retrieval-augmented-generation)
11. [pgvector — Vector Search in PostgreSQL](#11-pgvector--vector-search-in-postgresql)
12. [Jina AI Embeddings](#12-jina-ai-embeddings)
13. [Docker and Docker Compose](#13-docker-and-docker-compose)
14. [EC2 Deployment](#14-ec2-deployment)
15. [React Frontend Architecture](#15-react-frontend-architecture)
16. [Security Patterns Used](#16-security-patterns-used)
17. [Bug Fix Log](#17-bug-fix-log)
18. [Hybrid Extraction Architecture](#18-hybrid-extraction-architecture)
19. [Document Classifier](#19-document-classifier)
20. [Structural OCR — PaddleOCR PPStructure](#20-structural-ocr--paddleocr-ppstructure)
21. [Medical Validator](#21-medical-validator)
22. [Ontology Normalizer and Unit Conversion](#22-ontology-normalizer-and-unit-conversion)
23. [Vision LLM Tier](#23-vision-llm-tier)
24. [Fine-Tuning OpenBioLLM-8B](#24-fine-tuning-openbio-llm-8b)

---

## 1. Project Overview

Lumen takes a medical report or prescription (uploaded as a PDF or image), extracts the text, validates the values, and returns a plain-English explanation. It identifies abnormal lab values, explains what medicines are for, flags urgent issues, and suggests questions to ask the doctor.

The architecture has two distinct layers that must never be confused:

- **Extraction layer** — deterministic. Three tiered OCR paths all feed into the same medical validator and ontology normalizer. No LLM is involved until values are already validated.
- **Explanation layer** — generative. The LLM receives a pre-validated, structured `ExtractionResult` JSON and explains it. It never sees raw OCR text and therefore cannot hallucinate extraction facts.

The full stack is:

- **Backend**: FastAPI (Python) with a queue-based async worker
- **Database**: PostgreSQL with the pgvector extension for AI-powered search
- **Cache**: Redis for job results (AOF persistence so the queue survives container restarts)
- **AI (extraction)**: 4-tier OCR pipeline — pdfplumber, PaddleOCR PPStructure, Tesseract, Vision LLM
- **AI (explanation)**: Groq LLM (llama-3.3-70b-versatile) via pluggable provider layer; fine-tuning in progress on `aaditya/Llama3-OpenBioLLM-8B`
- **Embeddings**: Jina AI for RAG retrieval
- **Frontend**: React + TypeScript + Tailwind CSS
- **Infrastructure**: Docker Compose, deployed on AWS EC2
- **Fine-tuning module**: Offline DAPT + SFT pipeline using Unsloth QLoRA on Kaggle, publishing to HuggingFace Hub

---

## 2. FastAPI — The Backend Framework

### Simple explanation

FastAPI is a Python library for building web APIs. It automatically validates incoming data, generates documentation, and handles HTTP requests. Think of it as the "receptionist" — it receives your file, checks it is valid, and hands it off to the right department.

### How it is used in Lumen

The API has four main routes:

- `POST /upload` — accepts a PDF or image file, saves it to S3, creates a job record, pushes the job ID to Redis, returns the job ID
- `GET /status/{job_id}` — returns the current stage and progress percentage of the job
- `GET /result/{job_id}` — returns the full structured JSON explanation once the job is complete
- `GET /health` — confirms the service is alive

### The lifespan pattern (important technical detail)

FastAPI has a concept called a "lifespan context manager" — a block of code that runs once when the app starts and once when it shuts down. In Lumen it is used to run database migrations and start the job scheduler:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()       # run Alembic migrations
    scheduler.start()
    yield           # app runs here — handling requests
    scheduler.shutdown()
```

The `yield` keyword separates startup code (before) from shutdown code (after). This replaced the older `@app.on_event("startup")` pattern which FastAPI deprecated.

### Custom HTTP middleware

A middleware is a layer that wraps every request and response. Lumen adds custom `Cache-Control` headers depending on the route:

- `/status/` endpoints get `no-cache` — the progress changes frequently and should never be served from a browser cache
- `/result/` endpoints get `public, max-age=3600` — once a result is ready it is immutable, so it can be cached for one hour

---

## 3. Async Programming in Python

### Simple explanation

Normally Python runs one thing at a time. Async programming lets it pause one task (like waiting for a network response) and start another task during the wait. This means the server can handle many users at once without needing many threads.

### How it works in Lumen

The keyword `async def` marks a function as async. Inside it, `await` tells Python "pause here and let other things run while we wait."

The worker uses a combination of async and threads. The LLM call is truly async (the Groq client supports `await`). But OCR and file parsing are CPU-heavy code that was not written with async in mind — running them directly would block the entire server. The fix is `run_in_executor`, which runs them in a separate thread pool:

```python
raw_text = await loop.run_in_executor(_executor, extract_text, local_path)
```

This hands off `extract_text` to a `ThreadPoolExecutor` and awaits the result without blocking the main async loop.

### Semaphore for concurrency control

A Semaphore is a counter that limits how many things can run at once. The worker uses one to cap concurrent jobs:

```python
sem = asyncio.Semaphore(settings.WORKER_CONCURRENCY)
await sem.acquire()  # blocks if already at limit
asyncio.create_task(_guarded_process(sem, job_id))
```

`sem.release()` is always called in a `finally` block so a crashed job does not permanently reduce the capacity.

---

## 4. PostgreSQL and SQLAlchemy

### Simple explanation

PostgreSQL is the database where job records and results are stored. SQLAlchemy is the Python library that talks to it — instead of writing raw SQL strings, you define Python classes that map to database tables.

### Models in Lumen

There are four tables:

- `jobs` — one row per uploaded file (status, progress stage, file path, timestamps)
- `results` — one row per completed job (the full JSON explanation, confidence score, processing time)
- `feedback` — stores user ratings (not yet wired to the frontend)
- `medical_knowledge` — stores embedded knowledge chunks for RAG (explained in section 11)

### How SQLAlchemy sessions work

A "session" is a unit of work with the database. The pattern used in Lumen is:

1. Create a session: `db = SessionLocal()`
2. Query or write data
3. Commit changes: `db.commit()`
4. Always close in a `finally` block: `db.close()`

Never skip the `finally` close — a leaked session holds a database connection open and can exhaust the connection pool.

### JSONB in PostgreSQL

The `result_json` column stores the full AI-generated explanation as JSONB, which is PostgreSQL's binary JSON format. It compresses and indexes JSON efficiently. When SQLAlchemy does not natively know about `JSONB`, you use `.with_variant()` to tell it to use the PostgreSQL-specific type:

```python
result_json = Column(JSON().with_variant(JSONB(), "postgresql"))
```

---

## 5. Alembic — Database Migrations

### Simple explanation

A migration is a versioned script that modifies the database schema. Instead of manually running `ALTER TABLE` commands in production, Alembic tracks which scripts have run and applies only the new ones.

### How it works

Migrations live in `alembic/versions/`. Each file has a `revision` ID and a `down_revision` (the ID of the previous migration), forming a chain. When `init_db()` runs on startup, it calls `alembic upgrade head` programmatically, which applies all unapplied migrations in order.

Lumen has two migrations:

- `0001_initial_schema` — creates the `jobs`, `results`, and `feedback` tables
- `0002_pgvector_medical_knowledge` — enables the `vector` PostgreSQL extension and creates the `medical_knowledge` table

### Key lesson

Alembic migrations run automatically at startup. This means any mistake in a migration file will break every container restart. Always test migrations against a real database before pushing.

---

## 6. Redis — Queue and Cache

### Simple explanation

Redis is an in-memory data store — it keeps data in RAM, making it extremely fast. Lumen uses it for two separate purposes: a job queue and a result cache.

### As a job queue

When a user uploads a file, the API pushes the job ID into a Redis list. The worker uses `BRPOP` (blocking pop) to wait for IDs to appear in the list. `BRPOP` is "blocking" — it sits there waiting and returns immediately when something arrives, without wasting CPU on polling.

This decouples the API from the worker completely. The API does not know or care if the worker is running. The worker does not know or care how jobs arrived — it just processes whatever it finds in the queue.

### As a result cache

Once a result is ready, the worker stores the full JSON in Redis with a one-hour TTL (time-to-live). When the frontend polls `/result/{job_id}`, the API checks Redis first. If the result is there, it returns it immediately without touching PostgreSQL. This makes repeated fetches very fast and reduces database load.

### Fallback DB polling

If Redis goes down or a job ID is somehow lost from the queue, the worker has a database fallback loop. Every N seconds it queries PostgreSQL for any jobs that have been in `queued` status for more than 60 seconds and re-pushes them to the queue. This ensures no job is silently lost.

---

## 7. The Worker Pipeline

### Simple explanation

The worker is a separate process that runs an infinite loop. It picks up job IDs from Redis, processes each job through eight stages, and stores the result.

### The eight stages

Each stage updates the `jobs` table with the current `stage` name and a `progress` percentage (0-100). The frontend polls `/status/{job_id}` to display the progress bar.

```
Stage 1 — DOWNLOADING  (10%)
  Download the file from S3 to a temp directory.

Stage 2 — CLASSIFYING  (20%)
  Run the document classifier.
  Produces a DocumentProfile: tier suggestion, page count, scan quality,
  section types (lab table, ECG, echo, prescription).

Stage 3 — EXTRACTING  (40%)
  Route to the correct tier based on DocumentProfile:
    Tier 0 (digital PDF): pdfplumber → line-classifier parser → ExtractionResult
    Tier 1 (clean scan):  PaddleOCR PPStructure → cell mapper → ExtractionResult
    Tier 2 (complex):     Vision LLM with section-aware prompts → ExtractionResult

Stage 4 — VALIDATING  (55%)
  MedicalValidator checks every ExtractedValue:
    - Hard limits (physiologically impossible values → rejected)
    - Unit coherence (e.g. potassium cannot be in mg/dL)
    - Inter-test consistency (e.g. HbA1c < 5.7 with fasting glucose > 126 → flagged)
  Rejected values go to extraction_artifacts, not to the LLM.

Stage 5 — NORMALIZING  (65%)
  OntologyNormalizer resolves every test name to a canonical LOINC ID.
  Converts units to the canonical form (e.g. mmol/L HbA1c → %).
  Unifies reference ranges: catalog range takes precedence, document-extracted range as fallback.

Stage 6 — RETRIEVING  (75%)
  RAG: embed validated test names and fetch nearest medical knowledge chunks from pgvector.

Stage 7 — EXPLAINING  (90%)
  LLM receives ExtractionResult JSON — NOT raw OCR text.
  Explanation-only prompt: explain what each value means, what could cause it,
  what action to take. Confidence < 0.6 values are flagged to verify with a doctor.

Stage 8 — FINALIZING  (95%)
  result_sanitizer fixes any malformed fields.
  Store in Redis (TTL = settings.REDIS_RESULT_TTL_SECONDS) and PostgreSQL.
  Mark job as COMPLETED.
```

### Why the LLM no longer extracts

In the original design the LLM both extracted values from raw text _and_ explained them. This created an undetectable hallucination surface: the model could invent a value, assign a unit, and then generate a confident but entirely wrong explanation. By separating extraction (deterministic, auditable) from explanation (generative), any hallucination is now limited to the quality of the explanation — not the factual content of what was measured.

### Dead job recovery (crash resilience)

When the worker starts, it runs a "watchdog" that checks for jobs stuck in `processing` status. If a job has been processing for longer than the configured timeout, it means the previous worker process crashed mid-job. The watchdog re-queues these jobs for a second attempt.

---

## 8. OCR — Multi-Tier Text Extraction

### Simple explanation

OCR (Optical Character Recognition) converts images or scanned PDFs into machine-readable text. The challenge is that Indian lab reports come in wildly different formats: crisp digital PDFs (Thyrocare, Metropolis), cleanly scanned table reports, and degraded or multi-modal documents (handwritten, ECG strips, echo images). One OCR approach cannot handle all three well.

### Four-tier cascade

Lumen selects the tier based on the `DocumentProfile` from the classifier:

**Tier 0 — Native text (digital PDFs)**
pdfplumber extracts embedded text directly without any image conversion. This is the fastest and most accurate path. Most urban Indian lab reports are digital PDFs and hit this path. The output is a `List[PageContent]` where each page carries its lines separately, preserving structure for the parser.

**Tier 1 — Structural OCR (clean scans with tables)**
When pdfplumber returns no text, PaddleOCR PPStructure is used. Unlike regular OCR which reads the whole page as a flat string, PPStructure understands the spatial layout. It returns table cells — `<td>HbA1c</td><td>5.9</td><td>%</td><td>4.0-5.6</td>`. Each cell is OCR'd individually, which is dramatically more accurate than reading the full page.

**Tier 2 — Tesseract fallback**
For scanned pages that are not primarily tabular, Tesseract PSM 3 (auto page segmentation) is used at 300 DPI. Binarisation threshold was raised from 140 to 160 to reduce salt-and-pepper noise from laser-printed reports.

**Tier 3 — Vision LLM (complex/degraded/multi-modal pages)**
For pages where structural extraction fails or returns sparse output, or for specialised sections (ECG, echocardiography), the page image is sent to a vision-capable LLM. The prompt is section-specific — a lab table page gets a constrained JSON extraction prompt; an ECG page gets a prompt that asks only for printed machine measurements, not waveform interpretation. See section 23.

Tesseract is a native binary, so it must be installed in the Docker image:

```dockerfile
RUN apt-get install -y tesseract-ocr
```

PaddleOCR is a Python package but has sizeable dependencies (~500 MB). It is installed in the worker image, not the API image, since OCR only runs in the worker.

---

## 9. LLM Integration and Prompt Engineering

### Simple explanation

An LLM (Large Language Model) is an AI that reads text and generates text. In Lumen, the LLM's role changed significantly during development: it went from being both extractor and explainer (unreliable) to being a pure explainer of pre-validated data (reliable).

### Groq as the LLM provider

Groq provides fast LLM inference. The model used is `llama-3.3-70b-versatile` — a 70-billion parameter open-source model. It is called via an API that is compatible with OpenAI's SDK, meaning the same `openai` Python library works by just changing the `base_url`.

### The role shift: extraction → explanation only

Originally the LLM received raw OCR text and was asked to both extract lab values and explain them. This created a critical failure mode: the LLM could hallucinate a non-existent value (e.g., invent `Potassium: 22 mEq/L`) and then confidently explain it as a dangerous hyperkalaemia. Because the extraction and explanation were one step, there was no checkpoint to catch this.

Now the LLM receives a pre-validated `ExtractionResult` JSON. It never sees raw text. The system prompt instruction changed from `"Extract EVERY test result from raw_text"` to:

```
You are explaining pre-extracted, validated medical test results to an Indian patient.
The extraction and validation has already been done by a separate system.
You must NOT re-extract values. Your job: for each value provided, explain
what it means in simple Indian English, what could cause it, and what action
the patient should take.
For values with confidence < 0.6, note that this value had extraction uncertainty
and the patient should verify it with their doctor.
```

**What the LLM payload now contains:**

```json
{
  "validated_values": [
    {
      "test_name": "HbA1c",
      "value": "5.9%",
      "canonical_value": 5.9,
      "unit": "%",
      "reference_range": "4.0–5.6%",
      "status": "above_normal",
      "confidence": 0.94,
      "source_page": 4
    }
  ],
  "medicines": [],
  "document_metadata": {
    "hospital": "Apollo Hospitals",
    "date": "2026-04-15"
  }
}
```

The `raw_text` field that previously cut off at 8,000 characters is no longer in the payload.

**JSON repair heuristics**

LLMs do not always return clean JSON. The `parse_or_repair_json` function tries four strategies in order:
1. Direct `json.loads()`
2. Strip markdown fences (the LLM sometimes wraps JSON in triple backticks)
3. Extract from the first `{` to the last `}` in the response
4. Detect truncation (if the response does not end with `}`, the LLM hit its token limit)

### Dual-model routing

There is a lightweight model for simple cases and a heavy model (`llama-3.3-70b-versatile`) for complex reports. The router picks based on the estimated complexity of the extraction result.

---

## 10. RAG — Retrieval-Augmented Generation

### Simple explanation

An LLM knows a lot from its training data, but that knowledge has a cutoff date and can be imprecise for specialised domains. RAG (Retrieval-Augmented Generation) is a technique where you give the LLM relevant reference material alongside the question — like letting a student bring a textbook into an exam.

In Lumen, the "textbook" is a pre-built database of 730 chunks of medical knowledge: what each lab test measures, what abnormal values mean, how medicines work.

### The process

1. When a job arrives, the parsed data (test names, medicine names) is converted into a text query string.
2. That query string is embedded — converted into a list of 512 numbers (a vector) that captures its meaning.
3. The vector database (pgvector) finds the stored chunks whose vectors are closest to the query vector.
4. The top matching chunks are injected into the LLM prompt.
5. The LLM uses these chunks as authoritative reference when generating its explanation.

### Why not just rely on the LLM's training?

LLMs can hallucinate — invent plausible-sounding but incorrect facts. By grounding the response in retrieved chunks from a curated catalog (Lumen's own `tests.json` and `medicines.json`), the explanations are more accurate and traceable.

### Important distinction: RAG is not learning

Every time a document is processed, RAG retrieves from the same fixed knowledge base. The model does not update or improve from the document. The knowledge base only changes when someone explicitly re-runs the indexing script. This is called "static RAG" and is the standard production pattern because it is predictable and deterministic.

---

## 11. pgvector — Vector Search in PostgreSQL

### Simple explanation

A vector is a list of numbers. When you embed a piece of text (convert it to a vector), similar texts produce similar vectors — numbers that are mathematically close to each other. pgvector is a PostgreSQL extension that lets you store vectors in a table and search for the nearest ones efficiently.

### Why pgvector instead of a dedicated vector database

The original implementation used ChromaDB (a dedicated vector database). This was removed for two reasons:
- ChromaDB's Python dependencies (specifically `sentence-transformers`) pull in PyTorch, which is 4+ GB. The Docker image grew to 12.7 GB.
- Adding another stateful service (ChromaDB) increases operational complexity.

pgvector integrates into the existing PostgreSQL instance, which is already part of the stack. The API image dropped from 12.7 GB to 561 MB.

### How it is set up

The Docker image for PostgreSQL is `pgvector/pgvector:pg15` — a pre-built image that has the vector extension compiled in. The extension is then enabled per-database in the Alembic migration:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

The `medical_knowledge` table has a column typed `Vector(512)` — a list of 512 floats.

### How similarity search works

pgvector uses the cosine distance operator `<=>`:

```sql
SELECT content, (embedding <=> CAST(:qvec AS vector)) AS distance
FROM medical_knowledge
ORDER BY embedding <=> CAST(:qvec AS vector)
LIMIT 10
```

Cosine distance ranges from 0 (identical direction) to 2 (opposite direction). A threshold of 0.6 means: only return chunks that are at least 40% similar to the query.

### The CAST() syntax requirement (critical lesson)

SQLAlchemy's `text()` function processes named parameters (`:param_name`) before sending SQL to the database. PostgreSQL's type-cast syntax `::vector` also contains a colon, which confuses SQLAlchemy's parser.

Wrong — SQLAlchemy sees `:embedding` as a parameter name inside a string:
```sql
':embedding'::vector        -- SyntaxError
"'%s'::vector" % val        -- injection risk
```

Correct — `CAST()` is standard SQL and does not use colons:
```sql
CAST(:embedding AS vector)  -- works perfectly
CAST(:metadata AS jsonb)
```

---

## 12. Jina AI Embeddings

### Simple explanation

An embedding model converts text into a vector (a list of numbers). Similar texts produce similar vectors. Jina AI provides this as a cloud API — you send text, you receive vectors.

### Why Jina instead of a local model

Running a local embedding model (like `sentence-transformers/all-MiniLM`) requires PyTorch, which adds 4 GB to the Docker image. Jina AI's `jina-embeddings-v3` model is called via an HTTP API — no local model, no GPU, no PyTorch.

### Key parameters

- **Model**: `jina-embeddings-v3`
- **Dimensions**: 512 (number of floats per embedding)
- **Task**: `text-matching` — Jina accepts a task hint to tune the model for different use cases. Text-matching is appropriate for semantic search.
- **Batch size**: 64 — the Jina API processes up to 64 texts in one call. The indexing script batches all 730 chunks in groups of 64.
- **Truncate**: `True` — if a text is too long for the model's context window, truncate it rather than error

### The indexing script

`scripts/index_catalogs.py` reads `tests.json` and `medicines.json`, builds descriptive text chunks for each entry, and calls `index_documents()`. That function calls the Jina API in batches, then upserts all embeddings into the `medical_knowledge` table. It is a one-time operation run after each deployment.

---

## 13. Docker and Docker Compose

### Simple explanation

Docker packages an application and all its dependencies into a "container" — a lightweight, isolated environment that runs the same way on any machine. Docker Compose defines multiple containers and how they connect to each other.

### The five services

```
api         — FastAPI web server (port 8000)
worker      — Async job processor
postgres    — PostgreSQL 15 with pgvector
redis       — Queue and cache
ui          — Nginx serving the built React app (port 80)
```

### Multi-stage builds

The backend Dockerfiles use multi-stage builds to keep the final image small:

```dockerfile
FROM python:3.11-slim AS base
# ... install dependencies

FROM base AS runtime
# Copy only what is needed to run
```

The `slim` base image is a minimal Python image without documentation, test files, or extra utilities. Combined with removing `sentence-transformers` (and therefore PyTorch), this is how the API image shrank from 12.7 GB to 561 MB.

### Non-root user

Running as root inside a container is a security risk. If the container is compromised, the attacker has root on the container's virtual filesystem. Lumen creates a non-root user:

```dockerfile
RUN useradd --create-home appuser
USER appuser
```

### Health checks

A health check is a command Docker runs periodically to verify a container is alive. The PostgreSQL health check:

```yaml
healthcheck:
  test: ["CMD", "pg_isready", "-U", "lumen"]
  interval: 5s
  timeout: 5s
  retries: 5
```

Other services declare `depends_on` with `condition: service_healthy` — they wait for PostgreSQL to pass its health check before starting.

### Environment variable scoping (critical lesson)

Docker Compose supports `${VARIABLE}` substitution in the compose file itself. But this reads from the host machine's environment variables, not from any `env_file` declared under a service. If the variable is only defined inside the container's environment, it will be blank at compose-parse time.

This caused the PostgreSQL health check to fail silently — see Bug Fix 4 in section 17.

---

## 14. EC2 Deployment

### Simple explanation

EC2 (Elastic Compute Cloud) is an AWS service that provides virtual machines you can rent. Lumen runs on a single Ubuntu EC2 instance.

### Key lessons from this deployment

**Disk space management**

Docker images accumulate quickly. The original deployment with ChromaDB, PyTorch, and sentence-transformers used 4+ GB per image, filling the 29 GB disk. Useful commands:

```bash
docker system prune -af --volumes   # removes unused images, containers, volumes
docker images                       # list all images with sizes
df -h                               # check overall disk usage
```

**Environment file hygiene**

Multiple `.env` files in different locations caused confusion:
- Root `.env` (stale, old OpenAI key)
- `secrets/lumen.env` (backup, stale)
- `backend/.env` (correct, current)

Docker Compose was picking up the wrong values. Solution: delete all stale files, keep exactly one `backend/.env`, add root-level `*.env` to `.gitignore`.

**Verifying the deployment**

```bash
docker compose ps           # all containers should show "healthy" or "running"
docker compose logs api     # tail logs from the API service
docker compose exec api python -c "from app.core.config import settings; print(settings.JINA_API_KEY)"
```

---

## 15. React Frontend Architecture

### Simple explanation

The frontend is the user interface — the web page users see in their browser. It is built with React (a library for building UIs), TypeScript (JavaScript with type checking), Vite (a fast build tool), and Tailwind CSS (utility-based styling).

### Three-page flow

```
UploadPage       -- drag-and-drop file upload
    |
    v (after upload, job ID received)
ProcessingPage   -- polls /status/{job_id} every 2 seconds, shows progress bar
    |
    v (when status = completed)
ResultPage       -- displays the full explanation across four tabs
```

### Polling pattern

The frontend does not use WebSockets or server-sent events. It simply calls the API every 2 seconds with a GET request. This is "short polling" — simple to implement, easy to debug, and acceptable for a process that takes 10-30 seconds.

### Four result tabs

1. **Summary** — overall summary, urgency level, red flags
2. **Abnormal Values** — each out-of-range lab result with explanation and lifestyle advice
3. **Medicines** — each prescribed drug with purpose, mechanism, side effects, generic alternatives
4. **Next Steps** — doctor questions and action items

### Type safety with TypeScript

All API response shapes are defined as TypeScript interfaces in `types.ts`. If the API changes a field name, the TypeScript compiler immediately flags every place in the frontend that uses the old name. This catches integration errors before they reach users.

---

## 16. Security Patterns Used

### Timing-safe API key comparison

The original check used Python's `!=` operator: `if request_key != settings.API_KEY`. This is vulnerable to a timing attack — an attacker can measure how long the comparison takes. Equal strings take longer than unequal ones at the first differing byte, leaking information about what the correct key is. The fix:

```python
import hmac
if not hmac.compare_digest(request_key.encode(), settings.API_KEY.encode()):
    raise HTTPException(status_code=401)
```

`hmac.compare_digest` always takes the same amount of time regardless of where the strings differ.

### Separate admin token

Previously `/admin/cleanup` was guarded by the same `API_KEY` used on public routes. This means any user with a valid API key could trigger cleanup. A separate `ADMIN_TOKEN` config field now guards admin routes. These are rotated independently.

### CORS credentials and wildcard origins

Browser specification forbids `Access-Control-Allow-Credentials: true` together with `Access-Control-Allow-Origin: *`. Setting both causes browsers to reject the response silently. The fix: `allow_credentials=True` is only set when `ALLOWED_ORIGINS` does not contain `*`.

### Rate limiting on all routes

Rate limiting was initially only on `/upload`. The `/status/` and `/result/` endpoints were unprotected — a client could poll them thousands of times per second. Rate limiting was added to all three routes.

### Thread-safe singletons

The Redis client and LLM provider factory were module-level globals. In a multi-threaded worker, two threads could both find the global `None` and both create a new instance simultaneously, potentially creating two connections to the same resource. Double-checked locking with `threading.Lock()` ensures only one instance is ever created:

```python
if _instance is None:
    with _lock:
        if _instance is None:   # check again inside the lock
            _instance = create_instance()
```

### Lazy S3 client initialization

The S3 client was created at module import time. This meant that importing `storage.py` in a test environment (or local development without AWS credentials) would immediately attempt to authenticate with AWS and fail. The fix: wrap initialization in a `_get_s3()` function called only when actually needed.

### Redis AOF persistence

By default Redis stores data only in memory. A container restart loses all queued job IDs. Append-Only File (AOF) persistence writes every operation to disk — Redis can replay the log on restart and recover the queue. Enabled in `docker-compose.yml` with `command: redis-server --appendonly yes`.

### S3 for file storage

Uploaded files are stored in an S3 bucket, not on the server's local disk. This means:
- The server stays stateless — it can be restarted or replaced without losing files
- Files are not accessible via a public URL unless explicitly signed
- S3 handles durability and backup automatically

### Non-root Docker user

Described in section 13. Limits the blast radius of any container exploit.

### Scheduled cleanup

APScheduler runs a job periodically to delete old S3 files and expired database records. This limits data retention and prevents unbounded growth of stored medical files.

---

## 17. Bug Fix Log

Each bug is documented with: what the symptom was, what the root cause was, how it was fixed, and what the general lesson is.

---

### Bug 1 — Prescription dosages appearing as abnormal lab values

**Symptom**
A prescription uploaded by a user showed entries like `Magnesium Oxide — 1 tablet — abnormal` in the abnormal values tab. The value "1 tablet" was flagged with a severity of "moderate".

**Root Cause**
The LLM was given the raw text of a prescription and asked to fill out the full schema, which includes `abnormal_values`. It treated dosage quantities (e.g. "1 tablet", "60000 IU") as if they were numeric lab measurements and compared them against reference ranges.

**Fix — Two layers**

Layer 1 (prompt-level): Added explicit rules to the system prompt:

```
DOCUMENT TYPE RULE:
If the document is a PRESCRIPTION / DOCTOR's Rx:
  - abnormal_values MUST be []
  - normal_values MUST be []
  - Never put "1 tablet", "60000 IU", dosage amounts into abnormal_values
```

Layer 2 (code-level): Added `_is_dosage_value()` in `result_sanitizer.py` that scans the `value` field of every abnormal entry for dosage keywords:

```python
_DOSAGE_KEYWORDS = re.compile(
    r'\b(tablets?|tab|capsules?|cap|sachet|drop|drops|syrup|'
    r'injection|inj|patch|cream|ointment|gel|inhaler|spray|...)\b',
    re.IGNORECASE,
)
```

Any entry whose value matches this pattern is removed from `abnormal_values` regardless of what the LLM said.

Additionally, `result_sanitizer.py` checks the `document_type` field at the end:

```python
if "prescription" in doc_type or doc_type == "rx":
    data["abnormal_values"] = []
    data["normal_values"] = []
```

**Lesson**
Prompt engineering alone is not sufficient for safety-critical constraints. Important invariants (like "prescriptions have no lab values") must also be enforced in code as a hard filter after the LLM responds. Defense in depth: prompt first, code second.

---

### Bug 2 — Null fields in medicine entries

**Symptom**
The medicines tab was showing blank entries for `generic_name`, `mechanism`, `cost_saving_tip`, and `generic_alternative`. The LLM was returning `null` for these fields even when the information is well-known (e.g., Metformin's mechanism of action).

**Root Cause**
The system prompt did not clearly tell the LLM that these fields were required and expected to be filled from its own medical knowledge, not just from the document. The LLM defaulted to `null` when the information was not literally present in the uploaded report.

**Fix**
Added explicit instructions to the system prompt:

```
MEDICINE FIELDS RULE — use your medical knowledge, never leave these null:
- generic_name: official INN name (e.g. "Atorvastatin" for Lipitor)
- mechanism: how the drug works in 1-2 sentences in plain patient language
- generic_alternative: a cheaper Indian brand with dose (e.g. "Atorva 20mg by Cadila")
- cost_saving_tip: one practical India-specific tip (Jan Aushadhi stores, etc.)
```

**Lesson**
LLMs interpret "null is allowed" as "null is acceptable when unsure." If a field should always be filled, the prompt must say so explicitly and explain where the data should come from (the document vs. the model's own knowledge).

---

### Bug 3 — Docker images too large due to PyTorch (EC2 disk full)

**Symptom**
The EC2 instance ran out of disk space during `docker compose build`. The API Docker image was 12.7 GB. The instance had 29 GB total.

**Root Cause**
The original RAG implementation used `chromadb` and `sentence-transformers` to embed documents locally. `sentence-transformers` depends on PyTorch, which pulls in CUDA runtime libraries and `triton`. Combined, these added 4+ GB per image. With both the API and worker image, the build consumed most of the disk.

**Fix**
Architectural change: removed `sentence-transformers`, `chromadb`, and all local ML dependencies. Replaced with:
- Jina AI embeddings API (HTTP call — no local model)
- pgvector as the vector store inside the existing PostgreSQL container

API image: 12.7 GB → 561 MB
Worker image: ~5 GB → 981 MB

**Lesson**
External APIs for ML inference are far more practical than local models in constrained environments. PyTorch is enormous and requires GPU infrastructure to justify. For production applications that call an LLM API anyway, using a second embedding API adds negligible cost and eliminates gigabytes of dependencies.

---

### Bug 4 — Docker Compose `${POSTGRES_USER}` interpolated as blank

**Symptom**
All containers started, but the `api` and `worker` services stayed in "waiting for postgres to be healthy" state indefinitely. Checking `docker compose ps` showed postgres as "unhealthy."

**Root Cause**
The postgres health check in `docker-compose.yml` was:

```yaml
test: ["CMD", "pg_isready", "-U", "${POSTGRES_USER}"]
```

Docker Compose performs variable substitution on the compose file using the host machine's environment. `POSTGRES_USER` was defined in `backend/.env` (loaded into the container's environment via `env_file`), but Docker Compose reads it from the host shell, where it was not set. The result was:

```bash
pg_isready -U     # blank username — command fails
```

The container kept failing its health check because `pg_isready` with no username defaults to the OS user (`root` inside the container), which is not a valid PostgreSQL user.

**Fix**
Hardcode the username directly in the health check:

```yaml
test: ["CMD", "pg_isready", "-U", "lumen"]
```

**Lesson**
`${VARIABLE}` in a `docker-compose.yml` file resolves from the host environment, not from `env_file`. Variables that are only meaningful inside the container (like database credentials) must either be hardcoded in compose file references, or also exported to the host shell. For static values like a database username that never change between environments, hardcoding in the health check is the simplest and clearest option.

---

### Bug 5 — SQLAlchemy `::vector` syntax error in pgvector queries

**Symptom**
Running the catalog indexing script failed with:

```
sqlalchemy.exc.StatementError: (sqlalchemy.exc.CompileError)
Bind parameter ':embedding' without a value — SyntaxError at or near ":"
```

**Root Cause**
In PostgreSQL, you can cast a value to a type using the `::` syntax: `value::vector`. When used inside a SQLAlchemy `text()` block with named parameters (`:embedding`), the `:` in `::vector` is mistakenly interpreted as the start of another parameter name. SQLAlchemy tries to find a value for a parameter called `embedding` (from `::vector` → `:vector`), cannot find it, and raises a compile error.

The problematic pattern:

```sql
INSERT INTO medical_knowledge (embedding)
VALUES (':embedding'::vector)
-- SQLAlchemy sees ':embedding' and ':vector' as two parameters
```

**Fix**
Use standard SQL `CAST()` syntax instead, which has no colons:

```sql
INSERT INTO medical_knowledge (embedding)
VALUES (CAST(:embedding AS vector))
-- SQLAlchemy correctly identifies only ':embedding' as a parameter
```

Same fix applied to JSONB:

```sql
-- Wrong:  ':metadata'::jsonb
-- Right:  CAST(:metadata AS jsonb)
```

**Lesson**
When mixing SQLAlchemy `text()` with PostgreSQL-specific syntax, avoid any syntax that uses `:` for something other than named parameters. The `::` type cast is a PostgreSQL extension that SQLAlchemy's parser does not understand. The standard SQL `CAST(expr AS type)` syntax is always safe.

---

### Bug 6 — Stale root-level `.env` overriding correct configuration

**Symptom**
After updating `backend/.env` with new Jina and Groq API keys, the worker was still trying to connect to the old OpenAI endpoint and failing authentication. The correct keys were in `backend/.env` but the wrong keys were being loaded.

**Root Cause**
Three `.env` files existed in the repository:
1. `/.env` — root-level, stale (old OpenAI key, old ChromaDB settings)
2. `/secrets/lumen.env` — an old backup
3. `/backend/.env` — the correct, current configuration

Docker Compose was also reading the root `.env` because Docker Compose automatically loads a file named `.env` from the same directory as the compose file. Since `docker-compose.yml` is at the root, the root `.env` was being loaded first, and its values were overriding the correct ones.

**Fix**
- Deleted `/.env` (root-level)
- Deleted `/secrets/` directory
- Added `*.env` and `secrets/` to `.gitignore` to prevent re-creation
- Only `backend/.env` remains as the source of truth

**Lesson**
Docker Compose has automatic `.env` discovery — a file named `.env` in the compose file's directory is always loaded. When you have `env_file:` declarations and also a root `.env`, both are loaded and can conflict. Always keep exactly one env file per deployment environment and document its expected location clearly.

---

### Bug 7 — ChromaDB container marked unhealthy before it was ready (resolved by removal)

**Symptom**
In the earlier ChromaDB-based architecture, the API container was marked unhealthy because ChromaDB took about 25 seconds to initialise but the health check had no start period. Every attempt failed during the start-up window, and Docker marked it unhealthy before it was ready.

**Root Cause**
The health check `start_period` was not set. Without it, Docker starts counting failures from the moment the container starts, including during the normal initialisation window.

**Fix at the time**
Added `start_period: 30s` to the ChromaDB health check, giving the container 30 seconds to initialise before any failures are counted.

**Eventual resolution**
ChromaDB was removed entirely as part of the pgvector migration (Bug 3 fix). This bug no longer applies, but the lesson remains.

**Lesson**
Containers that have a slow startup phase (databases, ML servers) need `start_period` in their health check. Without it, Docker can mark a perfectly healthy container as failed during its normal boot sequence. Other services depending on it will then refuse to start.

---

---

## 18. Hybrid Extraction Architecture

### The core problem with a single pipeline

The original architecture had one pipeline that tried to handle everything: extract values from raw text and explain them. This failed in three compounding ways:

1. **OCR quality determines extraction quality**: A smudged scan produces noisy text, which confuses the parser, which passes garbage to the LLM, which hallucinates a plausible value. At no point was there a check that a value was physiologically possible.

2. **The LLM is not a reliable extractor**: LLMs are probabilistic. Given the same page, they sometimes extract 8 values and sometimes 6. They sometimes swap the value and reference range. They sometimes invent values from their training data when the actual text is ambiguous.

3. **No intermediate representation**: When extraction and explanation are one step, there is no auditable checkpoint. You cannot inspect what was extracted before explanation.

### The design principle

**Separate extraction (deterministic) from explanation (generative).** The extraction layer is a pipeline of code that can be tested with unit tests and regression fixtures. The explanation layer is a single bounded LLM call that receives clean structured input.

The intermediate representation `ExtractionResult` is the contract between these two layers. It carries every `ExtractedValue` with its source page, raw text, numeric value, unit, validator status, and confidence score.

```python
@dataclass
class ExtractedValue:
    test_id: str           # canonical LOINC-mapped ID: "hba1c"
    raw_name: str          # exactly as found: "Glycated Haemoglobin"
    raw_value: str         # exactly as found: "5.9%"
    value_numeric: float   # parsed float: 5.9
    unit: str              # normalized unit: "%"
    ref_range_raw: str     # as found: "4.0 - 5.6"
    source_page: int
    source_line: str
    extraction_tier: str   # "digital_text" | "paddle_table" | "vlm_cloud" | "vlm_local"
    validator_status: str  # "passed" | "clamped" | "flagged" | "rejected"
    confidence: float      # 0.0 – 1.0
```

**Lesson**: When an AI-generated result has safety implications, do not put the LLM in the extraction path. Build a deterministic extractor that the LLM cannot affect, then let the LLM work on clean validated data only.

---

## 19. Document Classifier

### What it does

The document classifier runs immediately after the file is downloaded. It produces a `DocumentProfile` that drives all downstream decisions: which extraction tier to use, what sections the document contains, how much to trust OCR output.

```python
@dataclass
class DocumentProfile:
    has_native_text: bool       # pdfplumber found embedded text
    native_text_ratio: float    # fraction of pages with native text
    page_count: int
    scan_quality: str           # "clean" | "moderate" | "degraded"
    has_tables: bool            # detected via whitespace alignment heuristics
    has_imaging: bool           # pages with very low text density
    detected_sections: List[str]  # ["lab_table", "ecg", "echo", "prescription"]
    suggested_tier: str         # "digital" | "structural_ocr" | "vision"
```

### How classification works

**`has_native_text`**: pdfplumber text extraction attempt. If more than 60% of pages return text, the document is digital.

**`scan_quality`**: For scanned pages, sample-render at 150 DPI and compute image variance. Low variance signals either a blank scan (underpopulated) or a black blob (degraded). A lightweight Tesseract pass measures per-character confidence scores and the ratio of high-confidence characters determines quality.

**`has_tables`**: Count whitespace-separated column alignment on at least three consecutive lines. This is a table. No ML needed — it is a spacing heuristic.

**`has_imaging`**: Pages where text density is below 20 tokens per page. Could be an ECG strip, X-ray scan, or graph.

**`detected_sections`**: Keyword triggers per page. First line keywords: "COMPLETE BLOOD COUNT" → `lab_table`. "ELECTROCARDIOGRAM" → `ecg`. "ECHOCARDIOGRAPHY" → `echo`. "Rx" or "Prescription" → `prescription`. These drive section-aware vision prompts.

**Why this matters**: Once you know a document has an ECG section, you can route that specific page to the vision tier with an ECG-specific prompt instead of a generic table extraction prompt. Section awareness turns one hard problem into several easier ones.

---

## 20. Structural OCR — PaddleOCR PPStructure

### The problem with reading tables as flat text

A lab report table has four logical columns: test name, value, unit, reference range. When Tesseract reads this as a flat page, it linearises everything left to right, top to bottom. A four-column table with 20 rows becomes 80 tokens in reading order: `HbA1c 5.9 % 4.0-5.6 Fasting Glucose 94 mg/dL 70-100...`. This is fine until columns misalign (common in low-quality scans), in which case values and names get transposed silently.

### What PPStructure does differently

PaddleOCR's PPStructure understands that a table is a 2D grid before it reads any text. It:

1. Detects the table bounding box using an object detection model
2. Identifies individual cell boundaries using a table structure model
3. Runs OCR on each cell independently
4. Returns the cells as an HTML table string

```html
<td>HbA1c</td><td>5.9</td><td>%</td><td>4.0-5.6</td>
```

Each OCR call is now on a small clean rectangular region containing 1-3 words. Accuracy goes from ~40% (PSM 6 on full page) to ~95% on per-cell recognition.

### Column mapping

The returned HTML table is parsed to identify which column corresponds to which field. The mapping is verified: column 0 must resolve to a known test alias, column 1 must parse as a number, column 2 must be a recognized unit string. If the mapping looks wrong, alternate column orderings are tried. This makes the pipeline robust to labs that put value before test name (some pathology formats do this).

### When to use it

PPStructure is used when the document classifier detects: no native text (`has_native_text=False`), scan quality is clean or moderate, and the page has tables. It is not used for image-only pages (ECG, X-ray) or for digital PDFs.

---

## 21. Medical Validator

### Why validation must be deterministic

If the validator were an LLM call, it would itself be subject to hallucination — you cannot use a probabilistic system to validate the output of another probabilistic system. All validation rules are deterministic Python code with no external dependencies.

### Three levels of checks

**Hard limits** — physiologically impossible values are unconditionally rejected:

```python
HARD_LIMITS = {
    "hba1c":     (2.0, 20.0),   # > 20% = OCR artifact
    "potassium": (1.5, 9.0),    # > 9 mEq/L = lethal, likely "9" OCR'd as "19"
    "sodium":    (100, 180),
    "glucose":   (10, 800),
    "hemoglobin": (2.0, 25.0),
    "wbc_count": (100, 200_000),
}
```

Rejected values are not silently dropped. They are moved to `extraction_artifacts` in the result, where the user can see that a value was detected but could not be validated. This is honest reporting.

**Unit coherence** — a value in the wrong unit class is flagged:

```python
UNIT_CLASSES = {
    "potassium":  {"mEq/L", "mmol/L"},    # NOT mg/dL
    "hba1c":      {"%", "mmol/mol"},       # IFCC or NGSP only
    "hemoglobin": {"g/dL", "g/L"},
}
```

**Inter-test consistency** — logical contradictions between values are flagged for human review:

```python
if hba1c.value < 5.7 and fasting_glucose.value > 126:
    flag("HbA1c normal range but fasting glucose diabetic — review extraction")
```

### What happens to rejected values

The user sees a note like "One value (Potassium: 22 mEq/L) was detected but failed physiological validation. Check the original report." This is far better than passing an impossible value to the LLM which then generates a confident but wrong explanation.

---

## 22. Ontology Normalizer and Unit Conversion

### The synonym problem

The same lab test has many names. "HbA1c", "Glycated Haemoglobin", "Glycosylated Hb", "A1c", "GHb" all refer to the same measurement. The parser might extract "Glycated Haemoglobin" from one lab and "A1c" from another. Without normalization, the RAG lookup and the LLM prompt would receive different strings for the same test, fragmenting the knowledge retrieval.

### Canonical ID resolution

The ontology normalizer maps every known name variant to a canonical ID derived from the LOINC standard:

```
"Glycated Haemoglobin" | "HbA1c" | "A1c" → "hba1c"
"Serum Creatinine" | "Creatinine" | "Cr"  → "creatinine"
```

The `synonyms.json` catalog contains 1,468 mappings. Resolution uses: exact match → alias match → fuzzy match (Levenshtein distance below threshold). The resolution confidence enters the per-value confidence score.

### Unit conversion

Some units express the same quantity in different scales. Before the LLM receives values, they are converted to the canonical form:

```python
UNIT_CONVERSIONS = {
    "hba1c": {
        "mmol/mol": lambda v: round((v / 10.929) + 2.15, 1),  # IFCC → NGSP %
    },
    "glucose": {
        "mmol/L": lambda v: round(v * 18.016, 1),  # mmol/L → mg/dL
    },
    "creatinine": {
        "μmol/L": lambda v: round(v / 88.4, 2),    # μmol/L → mg/dL
    },
}
```

The original value and unit are preserved in `raw_value`. The converted value goes into `value_numeric` and `unit`. The LLM always receives values in the canonical unit and never needs to perform unit arithmetic.

### Reference range unification

The catalog has curated reference ranges. The document also contains a printed reference range. The normalizer uses the catalog range as the authoritative source and the document range as a cross-check. If they differ by more than a configurable percentage, the discrepancy is noted in the result metadata.

**Lesson**: Normalization has to happen before the LLM sees anything. An LLM that receives `HbA1c 47 mmol/mol` (IFCC units, Nordic pathology format) will not reliably convert this to `6.5%` \u2014 it may convert it, may leave it, or may hallucinate an incorrect conversion. Code-based unit conversion is exact, testable, and free.

---

## 23. Vision LLM Tier

### When it activates

The vision tier activates for pages where all text-based extraction approaches fail or produce sparse output. Triggers:

- `scan_quality == "degraded"` — the classifier assessed the scan as low quality
- `has_imaging == True` — pages with <20 text tokens (ECG strips, graph images)
- Structural OCR returned fewer than 3 values from a page expected to have a full panel
- Sections detected: `ecg`, `echo` (these always route to vision regardless of scan quality)

### Section-aware prompting

Sending a 20-page PDF to one vision LLM call is expensive and inaccurate. Instead, each page is routed individually based on its detected section type:

**Lab table pages** — constrained JSON extraction prompt:
```
Return ONLY a JSON array for each row you can read:
[{"test_name": "...", "value": "...", "unit": "...", "ref_range": "..."}]
If a cell is unreadable, use null. Never guess or infer values.
Do not include any text outside the JSON array.
```

**ECG pages** — metadata-only prompt:
```
Extract ONLY the printed machine measurements from this ECG.
Return: {"heart_rate": ..., "rhythm": "...", "pr_interval_ms": ...,
         "qrs_duration_ms": ..., "qtc_ms": ..., "axis_degrees": ...,
         "machine_interpretation": "..."}
Do NOT interpret waveform morphology. Only extract values explicitly printed.
```

The narrow prompts reduce hallucination. A vision LLM asked only for numeric metadata cannot invent a rhythm interpretation — the prompt scope excludes it.

### Provider abstraction

The vision providers mirror the existing `llm_providers/` pattern exactly:

```
services/vision_providers/
    base.py              # VisionProvider ABC
    factory.py           # VISION_PROVIDER routing
    openai_vision.py     # GPT-4o / GPT-4o-mini
    gemini_vision.py     # Gemini 1.5 Flash
    local_vision.py      # Ollama (Qwen2-VL 7B / InternVL)
    vision_prompts.py    # section-specific prompt builders
```

### Local option for PHI compliance

`local_vision.py` calls Ollama's vision endpoint. Qwen2-VL 7B runs on 16 GB VRAM and outperforms GPT-4o-mini on document OCR benchmarks. Zero data leaves the hardware — relevant for enterprise deployments handling PHI (Personal Health Information).

Configuration:
```env
VISION_PROVIDER=local
VISION_ENDPOINT=http://localhost:11434
VISION_MODEL=qwen2-vl:7b
```

**Lesson**: Vision LLMs are not magic. They hallucinate less when constrained to narrow output schemas and specific page sections. Sending a full document to a single unconstrained vision call produces worse results than routing each page individually.

---

## 24. Fine-Tuning OpenBioLLM-8B

### Why fine-tune at all

The Groq-hosted `llama-3.3-70b-versatile` model gives good explanations but has two problems: it costs per token, and it cannot be deployed on-premise for PHI compliance. A fine-tuned 8B model that explains Indian lab reports specifically, in Indian English, with Jan Aushadhi references and local clinical context, is both cheaper and more relevant than a 70B general model.

### The base model

`aaditya/Llama3-OpenBioLLM-8B` (Apache 2.0 license) is a medical fine-tune of Meta's Llama 3 8B. It has been further trained on PubMed, medical textbooks, and clinical notes. Starting from this checkpoint rather than base Llama 3 means the first phase of training has less distance to cover.

### Two-phase training

**Phase 1 — DAPT (Domain-Adaptive Pre-Training)**

Standard causal language modelling on a corpus of Indian medical domain text, before any task-specific instruction is introduced. This shifts the model's token distribution toward:
- Indian drug brand names and dosage forms
- Indian reference range conventions (some labs report in different units)
- Indian pathology report section headers and layouts
- Clinical terminology from Indian epidemiology studies

The corpus has 41,218 records from three sources:
- PubMed abstracts filtered for India-relevant conditions (diabetes, anaemia, tuberculosis, cardiovascular)
- RxNorm drug descriptions expanded with Indian brand names
- Synthetic lab reports generated by `llama-3.1-8b-instant` via Groq free API

**Phase 2 — SFT (Supervised Fine-Tuning)**

The DAPT checkpoint is fine-tuned on instruction-following pairs. Each pair has:
- **Input**: a structured `ExtractionResult` JSON (what the Lumen extraction pipeline produces)
- **Output**: a plain-language explanation in Indian English (what the fine-tuned model must learn to produce)

SFT pairs are generated by a 3-call Groq pipeline per sample:
1. Simulate raw OCR extraction text for a plausible Indian lab report
2. Produce the structured `ExtractionResult` JSON (simulating what the deterministic pipeline would output)
3. Generate the patient-friendly explanation (the training target)

### QLoRA with Unsloth

Training 8B parameters from scratch would require hundreds of GPU-hours. QLoRA (Quantized Low-Rank Adaptation) freezes the base model weights at 4-bit precision and trains only a small set of adapter matrices (LoRA). The adapters are merged back into the base weights after training. This makes fine-tuning feasible on a single Kaggle T4 GPU (free).

Unsloth is a library that makes Llama QLoRA training roughly 2x faster than standard `transformers` + `peft` training, through hand-optimized kernels for attention and gradient operations.

Key hyperparameters:
- LoRA rank: 16, alpha: 32
- Batch size: 1 with gradient accumulation 16 (effective batch 16)
- Learning rate: 2e-4 with cosine schedule
- Max sequence length: 2048

### HuggingFace Hub checkpointing

The Kaggle notebook streams checkpoints to `PrajwalAmte/lumen-medical-8b` (private) every 50 training steps using `hub_strategy="checkpoint"`. This means a Kaggle session timeout does not lose all progress — training can resume from the last checkpoint uploaded to the Hub.

### Data collection scripts

```bash
cd training

# PubMed abstracts — no key needed, uses Entrez E-utilities
python collect_all.py --pubmed

# Drug descriptions from RxNorm catalog — no key needed
python collect_all.py --drugs

# Synthetic SFT pairs via Groq free tier (~120/day, 500K token/day limit)
python collect_all.py --synthetic --count 120 --groq-key gsk_YOUR_KEY

# Deduplicate and merge all sources into dapt_corpus.jsonl
python collect_all.py --deduplicate
```

### DailyQuotaError and resumption

The Groq free tier has a 500K token/day limit. The synthetic collector tracks this and raises `DailyQuotaError` when the limit is reached. The orchestrator catches this, saves progress, and prints a resume command so collection continues from where it left off the next day rather than starting over.

**Lesson**: Fine-tuning is not a silver bullet. It improves explanation quality and cultural relevance, but it does not fix extraction errors — that is the validator's job. A fine-tuned model that receives bad input will produce wrong explanations confidently. The extraction → validation → explanation separation must be maintained even if you swap in a fine-tuned model for the explanation step.

---

### Bug 8 — Timing attack on API key comparison

**Symptom**
No visible symptom. Identified during security review.

**Root Cause**
The API key check used Python's `!=` operator: `if provided_key != settings.API_KEY`. Python strings are compared byte by byte and return False immediately at the first mismatch. An attacker sending thousands of requests can measure response times to determine, byte by byte, what the correct API key is. This is a timing side-channel attack.

**Fix**

```python
import hmac
if not hmac.compare_digest(
    provided_key.encode("utf-8"),
    settings.API_KEY.encode("utf-8")
):
    raise HTTPException(status_code=401)
```

`hmac.compare_digest` always compares the full string regardless of where the first mismatch occurs, taking constant time.

**Lesson**
Secret comparison must always use constant-time comparison. Python's string `==` and `!=` are fast but not timing-safe. `hmac.compare_digest` is in the standard library and has no additional dependencies.

---

### Bug 9 — CORS `allow_credentials=True` with wildcard origin rejected by browsers

**Symptom**
In certain browser/CORS configurations, API responses were rejected silently. No error appeared in the application, but authenticated cross-origin requests failed.

**Root Cause**
The CORS middleware was configured with both `allow_origins=["*"]` (wildcard) and `allow_credentials=True` simultaneously. This violates the browser CORS specification: a response with `Access-Control-Allow-Origin: *` and `Access-Control-Allow-Credentials: true` is forbidden by the spec. Browsers drop such responses.

**Fix**
`allow_credentials=True` is conditional on whether `ALLOWED_ORIGINS` contains a wildcard:

```python
allow_credentials = "*" not in settings.ALLOWED_ORIGINS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=allow_credentials,
)
```

In production where specific origins are listed, credentials work. In development with `["*"]`, credentials are disabled but all requests still succeed.

**Lesson**
Read the CORS spec. The credential + wildcard combination is a common mistake because both settings appear to "work" in most simple tests, but fail in specific browser security contexts. If you need credentials (cookies, Authorization headers), you must list exact origins.

---

### Bug 10 — Job lifecycle deleting files for active jobs

**Symptom**
Occasionally, a job in progress would fail with an S3 `NoSuchKey` error mid-processing. The file had been deleted while the worker was still reading it.

**Root Cause**
The `delete_old_job_files` scheduler function queried for jobs older than N days without filtering by status. It would find jobs in `processing` or `queued` status (e.g. large reports that took longer than expected) and delete their S3 files.

**Fix**
Added a status filter to the query:

```python
jobs = db.query(Job).filter(
    Job.created_at < cutoff,
    Job.status.in_(["completed", "failed", "expired"])
).all()
```

Only terminal-state jobs are eligible for file deletion.

**Lesson**
Cleanup queries on time alone are dangerous. Time + terminal status is the correct predicate. A job that is still in progress should never be touched by a cleanup scheduler, no matter how old it is.

---

### Bug 11 — Redis result TTL mismatch between setting and code

**Symptom**
Results disappeared from Redis after 1 hour, but the configured `REDIS_RESULT_TTL_SECONDS` was set to 86400 (24 hours). Users returning to check their result after a few hours found it gone and the API falling back to PostgreSQL.

**Root Cause**
The worker set the Redis TTL with a hardcoded literal:

```python
redis_client.setex(cache_key, 3600, json.dumps(result))
```

The `settings.REDIS_RESULT_TTL_SECONDS` setting existed and was correctly loaded by pydantic, but was never referenced here. The literal `3600` overrode whatever the operator configured.

**Fix**

```python
redis_client.setex(cache_key, settings.REDIS_RESULT_TTL_SECONDS, json.dumps(result))
```

**Lesson**
Constants are only useful if they are actually used. Hardcoded literals inside business logic invalidate configuration settings silently. Any value that an operator might reasonably want to tune (timeouts, TTLs, batch sizes) belongs in settings, and only in settings, with no fallback literal in code.

---

*End of Learnings.md*
