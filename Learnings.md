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
8. [OCR — Extracting Text from Documents](#8-ocr--extracting-text-from-documents)
9. [LLM Integration and Prompt Engineering](#9-llm-integration-and-prompt-engineering)
10. [RAG — Retrieval-Augmented Generation](#10-rag--retrieval-augmented-generation)
11. [pgvector — Vector Search in PostgreSQL](#11-pgvector--vector-search-in-postgresql)
12. [Jina AI Embeddings](#12-jina-ai-embeddings)
13. [Docker and Docker Compose](#13-docker-and-docker-compose)
14. [EC2 Deployment](#14-ec2-deployment)
15. [React Frontend Architecture](#15-react-frontend-architecture)
16. [Security Patterns Used](#16-security-patterns-used)
17. [Bug Fix Log](#17-bug-fix-log)

---

## 1. Project Overview

Lumen takes a medical report or prescription (uploaded as a PDF or image), extracts the text, sends it to an AI model, and returns an explanation that a non-medical person can understand. It identifies abnormal lab values, explains what medicines are for, flags urgent issues, and suggests questions to ask the doctor.

The full stack is:

- **Backend**: FastAPI (Python) with a queue-based async worker
- **Database**: PostgreSQL with the pgvector extension for AI-powered search
- **Cache**: Redis for job results
- **AI**: Groq LLM (llama-3.3-70b-versatile) + Jina AI for embeddings
- **Frontend**: React + TypeScript + Tailwind CSS
- **Infrastructure**: Docker Compose, deployed on AWS EC2

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

The worker is a separate process that runs an infinite loop. It picks up job IDs from Redis, processes them through a pipeline of steps, and stores the result.

### The five stages

Each stage updates the `jobs` table with the current `stage` name and a `progress` percentage (0-100). The frontend polls `/status/{job_id}` to display the progress bar.

```
Stage 1 — EXTRACTING_TEXT  (20%)
  Download the file from S3 to a temp directory.
  Run OCR to convert the PDF/image into raw text.
  Delete the temp file.

Stage 2 — PARSING  (40%)
  Use regex and simple rules to extract structured data:
  test names, values, units, and medicine names from the raw text.
  This gives the LLM a head start — it does not have to parse from scratch.

Stage 3 — GENERATING_EXPLANATION  (70%)
  Call the pgvector database to find relevant medical knowledge chunks (RAG).
  Send the raw text + parsed data + RAG context to the Groq LLM.
  The LLM returns a structured JSON explanation.

Stage 4 — FINALIZING  (90%)
  Run the result through result_sanitizer to fix any malformed fields.
  Store the result in Redis and PostgreSQL.
  Mark the job as COMPLETED.
```

### Dead job recovery (crash resilience)

When the worker starts, it runs a "watchdog" that checks for jobs stuck in `processing` status. If a job has been processing for longer than the configured timeout, it means the previous worker process crashed mid-job. The watchdog re-queues these jobs for a second attempt.

---

## 8. OCR — Extracting Text from Documents

### Simple explanation

OCR (Optical Character Recognition) converts images or scanned PDFs into machine-readable text. Without this step, the AI would receive a binary blob it cannot understand.

### Two-layer approach

Lumen tries two methods in order:

1. **pdfplumber** — extracts text directly from PDFs that already have embedded text (digital PDFs). This is fast and perfectly accurate.

2. **pdf2image + Tesseract** — if pdfplumber returns empty text (scanned or image-based PDFs), the PDF is converted to images using `pdf2image`, and each image is passed to Tesseract OCR. Tesseract is a free, open-source OCR engine developed by Google. It reads pixel patterns and recognises characters.

Tesseract is a native binary (not a Python package), so it must be installed in the Docker image:

```dockerfile
RUN apt-get install -y tesseract-ocr
```

---

## 9. LLM Integration and Prompt Engineering

### Simple explanation

An LLM (Large Language Model) is an AI that reads text and generates text. In Lumen, the LLM reads the medical document and generates the structured JSON explanation that the frontend displays.

### Groq as the LLM provider

Groq provides fast LLM inference. The model used is `llama-3.3-70b-versatile` — a 70-billion parameter open-source model. It is called via an API that is compatible with OpenAI's SDK, meaning the same `openai` Python library works by just changing the `base_url`.

### Prompt engineering — the hard part

Prompting is the art of writing instructions that reliably steer the LLM toward the correct output format and reasoning. Lumen uses a system prompt and a user prompt.

**The system prompt** defines the AI's persona and rules. Key rules in Lumen's system prompt:

- Output only valid JSON — no markdown fences, no prose
- Copy values and units exactly as written — never convert units
- Extract every test result — not just the first few
- Compare each value against its reference range strictly — if above or below, it is abnormal
- Document type rule — if the document is a prescription, `abnormal_values` and `normal_values` must be empty arrays because prescriptions contain dosages, not lab measurements

**The user prompt** contains the actual data:

```
Analyse the medical document below and return a JSON matching the schema.

Input: { parsed_data: {...}, raw_text: "..." }

Relevant medical knowledge (RAG context):
---
Haemoglobin: measures oxygen-carrying capacity...
---
```

**JSON repair heuristics**

LLMs do not always return clean JSON. The `parse_or_repair_json` function tries four strategies in order:
1. Direct `json.loads()`
2. Strip markdown fences (the LLM sometimes wraps JSON in triple backticks)
3. Extract from the first `{` to the last `}` in the response
4. Detect truncation (if the response does not end with `}`, the LLM hit its token limit)

### Dual-model routing

There is a lightweight model (`gpt-oss-20b`) for simple cases and a heavy model (`llama-3.3-70b-versatile`) for complex reports. The router picks based on the estimated complexity of the parsed data.

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

### API key guard on admin routes

The `/admin/cleanup` endpoint is protected by checking a request header against `settings.ADMIN_API_KEY`. If the header is missing or wrong, the request is rejected with 401 Unauthorized. This prevents any public user from triggering data cleanup.

### CORS

CORS (Cross-Origin Resource Sharing) controls which websites can call the API. In development, all origins are allowed. In production, only the specific frontend domain should be listed.

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

*End of Learnings.md*
