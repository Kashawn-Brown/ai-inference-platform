# Architecture

This document is the detailed system view of the AI Inference Platform. The
[README](../README.md) is the quickstart — overview, stack table, API table, and
how to run it. This doc covers the runtime behavior the README leaves out: how a
request actually flows, how a batch job moves through its lifecycle, what the data
model looks like, how telemetry is wired, and how the whole thing is deployed.

The system has two independent paths over one model server. **Live requests** go
through a synchronous FastAPI gateway and come straight back. **Batch jobs** are
persisted to Postgres and drained asynchronously by a background worker. Gateway
and worker are one Python package (`aiinfra`) with two process entrypoints; they
share the DB layer, config, the vLLM client, schemas, and observability
primitives, but run as separate containers and never call each other.

---

## System context

Clients reach only the gateway. The gateway serves live inference itself (calling
vLLM) and records batch work to Postgres. The worker reads that work back out of
Postgres and processes it by calling vLLM **directly** — never through the gateway.
Prometheus scrapes a `/metrics` endpoint on both the gateway and the worker;
Grafana reads from Prometheus; k6 drives the gateway during benchmark runs.

```mermaid
flowchart LR
    Client["Client"]
    k6["k6 (benchmarks)"]

    subgraph platform["AI Inference Platform"]
        Gateway["FastAPI Gateway"]
        Worker["Worker (batch loop)"]
        vLLM["vLLM Server<br/>Qwen2.5-1.5B-Instruct"]
        PG[("Postgres")]
    end

    subgraph obs["Observability"]
        Prom["Prometheus"]
        Graf["Grafana"]
    end

    Client -->|"POST /v1/inference, /v1/batch/*"| Gateway
    k6 -->|"load"| Gateway
    Gateway -->|"HTTP (live inference)"| vLLM
    Gateway -->|"SQL (batch CRUD, config reads)"| PG
    Worker -->|"SQL (claim items, write results)"| PG
    Worker -->|"HTTP (direct)"| vLLM

    Prom -.->|"scrape /metrics"| Gateway
    Prom -.->|"scrape /metrics"| Worker
    Graf -->|"query"| Prom
```

---

## Components

Each component owns a narrow slice. The boundaries below are the contract — what
each one is responsible for, what it depends on, and what it deliberately does not
do.

**FastAPI Gateway.** Owns the HTTP layer: request validation (Pydantic v2),
response shaping, batch-job CRUD, and gateway-side logs and metrics. Calls vLLM
for live inference and Postgres for batch CRUD and config reads. Does **not**
process batch items, own model-serving logic, or schedule the worker.

**Worker.** Owns the batch execution loop: claim queued items, process them
against vLLM, persist results, and update progress and terminal status. Calls
Postgres and vLLM directly. Exposes no external API — only a local `/metrics`
endpoint for Prometheus. A single worker process in v1; the claim mechanism is
already safe for horizontal scaling later.

**vLLM Server.** Owns model inference and nothing else. Serves
Qwen2.5-1.5B-Instruct over an OpenAI-compatible HTTP API
(`/v1/chat/completions`). Knows nothing about jobs, items, or persistence.

**Postgres.** Owns `batch_jobs`, `batch_job_items`, and `model_configs`. Does
**not** store live request bodies or responses, benchmark results, or session
state — live data lives in logs and metrics, benchmark results live as artifact
files.

**Observability layer.** Prometheus scrapes both processes; Grafana dashboards
read from Prometheus; structured JSON logs go to stdout and are captured via
container logs; correlation IDs thread request and item identity through the logs.
No OpenTelemetry.

---

## Live inference path

A single `POST /v1/inference` is fully synchronous. The gateway binds a
correlation ID (honoring an inbound `X-Request-ID` or generating one), validates
the body, calls vLLM through a shared async httpx client, shapes the response, and
emits exactly one structured log line plus metrics on the way out — on success and
on every mapped failure alike.

The vLLM client maps transport and protocol failures to typed errors at the
boundary, and the route maps those to HTTP status codes: a timeout becomes **504**,
an unreachable server **503**, and a malformed or non-2xx reply **502**.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant G as Gateway
    participant V as vLLM

    C->>G: POST /v1/inference {prompt, max_tokens, temperature}
    Note over G: bind correlation ID,<br/>validate (Pydantic)
    G->>V: POST /v1/chat/completions
    alt success
        V-->>G: completion + token usage
        G-->>C: 200 {request_id, model, output, usage, latency_ms}
    else timeout / unreachable / bad reply
        V--xG: error at client boundary
        G-->>C: 504 / 503 / 502
    end
    Note over G: one JSON log line + metrics<br/>(status, latency_ms)
```

---

## Batch job path

Submission and execution are decoupled. `POST /v1/batch/jobs` resolves the model
(from the active config, or validates a supplied one), then persists the job and
all its items as `queued` in a single transaction and returns `201` immediately —
the gateway only records the work. The worker drains it on its own clock.

The worker loop claims one item at a time with `SELECT ... FOR UPDATE SKIP LOCKED`
over queued items — the Postgres-as-queue mechanism, no Redis. It flips the item
(and its job, once) to `running`, **commits to release the row lock before** the
slow vLLM call, then processes the item: one retry on a transient error
(timeout/connection), immediate fail otherwise. On success it writes the
`output_payload`; either way it bumps the job's `completed_items`/`failed_items`,
and when every item is accounted for it sets the terminal status — `failed` only
if nothing succeeded, otherwise `completed`.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant G as Gateway
    participant PG as Postgres
    participant W as Worker
    participant V as vLLM

    C->>G: POST /v1/batch/jobs {name, items[]}
    G->>PG: INSERT job + items (status=queued), one txn
    G-->>C: 201 BatchJob {status: queued}

    loop until queue dry
        W->>PG: SELECT ... FOR UPDATE SKIP LOCKED (oldest queued)
        W->>PG: item + job -> running, COMMIT (release lock)
        W->>V: POST /v1/chat/completions (1 retry on transient)
        V-->>W: completion / error
        W->>PG: write output_payload, bump progress
        W->>PG: set terminal status when all items done
    end
```

### Job and item lifecycle

A job's status is derived from its items. An item is `queued` until claimed,
`running` while being processed, then `completed` or `failed`. A job follows the
same path and lands on `completed` or `failed` depending on whether any item
succeeded; `cancelled` is a defined terminal state for jobs but is not driven by
the worker in v1.

```mermaid
stateDiagram-v2
    direction LR
    state "Job" as J {
        [*] --> queued
        queued --> running: worker claims first item
        running --> completed: ≥1 item succeeded
        running --> failed: all items failed
        running --> cancelled: (reserved, not v1)
    }
    state "Item" as I {
        [*] --> queued_i: queued
        queued_i --> running_i: running
        running_i --> completed_i: completed
        running_i --> failed_i: failed (retry exhausted / non-transient)
    }
```

---

## Data model

Three tables. `batch_jobs` and `batch_job_items` are a strict parent/child FK
relationship. `model_configs` is referenced by `batch_jobs.model_name` logically —
by name, not a database foreign key — so a job records which model it ran against
without coupling job rows to config-row lifetimes. A composite index on
`batch_job_items (batch_job_id, status)` backs the worker's claim query.

What is **not** here is as deliberate as what is: no live request bodies or
responses (those are logs and metrics), no benchmark results (artifact files), no
session or conversation state (out of scope).

```mermaid
erDiagram
    batch_jobs ||--o{ batch_job_items : contains
    model_configs ||..o| batch_jobs : "referenced by name"

    batch_jobs {
        uuid id PK
        text name
        text submitted_by "loose operational id, not a tenant"
        text model_name "logical ref to model_configs"
        text job_type
        text status "queued|running|completed|failed|cancelled"
        int total_items
        int completed_items
        int failed_items
        timestamptz created_at
        timestamptz started_at
        timestamptz completed_at
        timestamptz updated_at
    }

    batch_job_items {
        uuid id PK
        uuid batch_job_id FK
        int item_index
        jsonb input_payload
        jsonb output_payload
        text status "queued|running|completed|failed"
        text error_message
        timestamptz created_at
        timestamptz updated_at
    }

    model_configs {
        uuid id PK
        text model_name UK
        text provider_type "vllm in v1"
        text serving_mode "local in v1"
        int max_tokens_default
        int timeout_ms
        int concurrency_limit
        boolean is_active
        timestamptz created_at
        timestamptz updated_at
    }
```

`model_configs` is the source of truth for model resolution — seeded with the
single active Qwen config by migration `0001`, not read from an env var at request
time.

---

## Observability

Three layers, one identity thread running through them.

**Structured logs.** Every process logs JSON to stdout via a custom
`JsonFormatter` — minimum `ts/level/logger/msg`, with per-request and per-item
fields merged in. The gateway emits one line per inference request
(`request_id`, `status`, `latency_ms`, token usage on success); the worker logs
per-item outcomes and the vLLM retry warning.

**Metrics.** Both processes expose Prometheus text on `/metrics` — the gateway via
a route, the worker via a small WSGI server on a daemon thread (port `9101`) so a
scrape can never block the claim/process cycle. The metric set is deliberately
small, with no redundant counters: the error count is the non-`ok` slice of a
labeled counter, and the items-processed count is a histogram's `_count`.

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `aiinfra_inference_requests_total` | counter | `status` | Live requests by outcome (errors = `status != "ok"`) |
| `aiinfra_inference_request_duration_seconds` | histogram | `status` | Gateway-measured request latency |
| `aiinfra_batch_jobs_total` | counter | `status` | Jobs reaching a terminal status |
| `aiinfra_batch_item_processing_duration_seconds` | histogram | `status` | Per-item processing time (`_count` = items processed) |
| `aiinfra_batch_queue_lag_seconds` | gauge | — | Age of the oldest queued item; 0 when empty |

**Correlation IDs.** A `contextvars` store plus a logging filter stamp
`request_id`/`job_id`/`item_id` onto every record automatically, so a request or
item is traceable across all the lines it produces — not just hand-instrumented
ones. The gateway binds the ID in a pure-ASGI middleware (chosen over
`BaseHTTPMiddleware` for contextvar visibility) and echoes it on the response
header; the worker binds `job_id`/`item_id` per item. IDs stay in logs and never
become Prometheus labels — that would blow up metric cardinality.

Grafana loads its datasource and three starter dashboards (gateway, worker, system
overview) from provisioning files on boot, so the dashboards are version-controlled
rather than clicked together by hand.

---

## Deployment topology

The reference environment is a Docker Compose stack — the same one `docker compose
up` brings up. Gateway and worker are built from `docker/`; the rest are stock
images. The `hf_cache` named volume persists the ~3GB Qwen download across
`compose down`, and a `postgres_data` volume persists job state. The k6 service is
gated behind a `bench` profile so it stays off `make up` and CI, only running on
`make bench-*`.

```mermaid
flowchart TB
    subgraph compose["Docker Compose network"]
        GW["gateway<br/>:8000"]
        WK["worker<br/>/metrics :9101"]
        VL["vllm<br/>:8000 (GPU)"]
        PG[("postgres:16<br/>:5432")]
        PR["prometheus<br/>:9090"]
        GR["grafana<br/>:3000"]
        K6["k6<br/>(profile: bench)"]
    end

    HF[("hf_cache volume")]
    PD[("postgres_data volume")]

    GW --> VL
    GW --> PG
    WK --> VL
    WK --> PG
    VL --- HF
    PG --- PD
    PR -.-> GW
    PR -.-> WK
    GR --> PR
    K6 --> GW
```

### Hardware constraints and what production would change

The documented baselines were measured on a 4GB GTX 1650 Ti — a Turing card with
**no tensor cores** — and the vLLM flags reflect that constraint rather than a
production tuning. On this hardware the platform sustains roughly **2 concurrent
requests / ~0.5 req/s**; the bottleneck is per-request decode latency (no tensor
cores, eager execution), not the batch-size cap. The current settings are:

- `--dtype float16`, `--enforce-eager` — eager execution skips CUDA-graph capture,
  which a 4GB card can't spare memory for; it costs latency.
- `--gpu-memory-utilization 0.78` — low because the Windows desktop already
  consumes ~780MB of the 4GB card, leaving little KV-cache headroom.
- `--max-model-len 2048`, `--max-num-seqs 8` — small context and batch window to
  fit the available VRAM.
- `--attention-config.backend TRITON_ATTN` — the default FlashInfer backend needs
  tensor cores this card lacks.

A production deployment would change the hardware first and the flags as a
consequence: a tensor-core GPU (Ampere or newer) with enough VRAM to **drop
`--enforce-eager`** (re-enabling CUDA graphs), raise `--gpu-memory-utilization`
toward 0.90+, increase `--max-model-len` and `--max-num-seqs` to use the larger
KV cache, and let vLLM pick its default attention backend. The
`model_configs.concurrency_limit` and the 30s client timeout would be retuned to
the measured capacity of that hardware. None of this changes the architecture —
only the serving parameters and the numbers in the benchmark baselines.

---

## Key design decisions

Terse pointers to the locked calls; each is settled, not open for relitigation.

- **vLLM, single-model, not multi-provider routing** — the focus is the inference
  layer, not a provider-abstraction shim. No per-request model override in v1.
- **Postgres `SELECT FOR UPDATE SKIP LOCKED` as the queue, not Redis** — adding a
  broker would be infrastructure for its own sake at this scale.
- **Correlation IDs in structured logs, not OpenTelemetry** — sufficient
  traceability without the operational weight.
- **Stateless live requests** — conversation memory and orchestration belong to
  the calling application, not this platform.
- **Benchmark results as artifact files, not a DB table** — Postgres holds batch
  state only; benchmark output lives in `benchmarks/results/`.
- **Docker Compose as the reference environment** — Kubernetes is deployment
  surface, not project scope.
</content>
</invoke>
