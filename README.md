# AI Inference Platform

A self-hosted inference platform that sits between applications and a model. Live requests flow through a FastAPI gateway; batch jobs run through a background worker; both talk to vLLM serving an open-weight model. Postgres holds job state. Prometheus + Grafana + structured logs make it observable.

## Why

Most "AI platforms" are either a thin wrapper around a hosted API or an enterprise product weighed down by every feature its largest customer ever asked for. This project is neither. It's a small, deliberately-scoped system that does inference well — synchronous for live calls, asynchronous for batch — with the operational surface (metrics, logs, health checks, benchmarks) you'd actually want in front of a model in production.

## What it does

**Live inference.** Clients hit a single endpoint. Requests are validated, forwarded to vLLM, and the response comes back synchronously. Latency, throughput, and errors are visible through Prometheus metrics and structured JSON logs, correlated by request ID.

**Batch jobs.** Clients submit a job with N items. A background worker claims items from Postgres and processes them against vLLM, persisting per-item results. Job status and per-item outputs are queryable through the API. Failure is isolated per item — one bad input doesn't fail the job.

## Architecture

```
┌──────────┐     POST /v1/inference     ┌──────────┐    HTTP    ┌──────────┐
│  Client  │ ─────────────────────────▶ │ FastAPI  │ ─────────▶ │   vLLM   │
└──────────┘                            │ Gateway  │            │  Server  │
                                        └────┬─────┘            └─────▲────┘
                                             │                        │
                                             │ SQL                    │ HTTP
                                             ▼                        │
                                        ┌──────────┐                  │
                                        │ Postgres │ ◀────────────┐   │
                                        └──────────┘              │   │
                                             ▲                    │   │
                                             │ SQL                │   │
                                        ┌────┴─────┐              │   │
                                        │  Worker  │ ─────────────┴───┘
                                        └──────────┘
```

The worker calls vLLM directly — never through the gateway. Live request data lives in logs and metrics; only batch state lives in Postgres.

## Stack

| Layer | Choice |
|---|---|
| Gateway | FastAPI + Uvicorn |
| Worker | Plain Python loop |
| Model serving | vLLM, serving Qwen2.5-1.5B-Instruct |
| Database | PostgreSQL 16 + SQLModel + Alembic |
| HTTP client | httpx |
| Validation | Pydantic v2 |
| Config | Pydantic Settings (env-driven) |
| Metrics | Prometheus + Grafana |
| Logs | Structured JSON to stdout |
| Tracing | Correlation IDs |
| Worker queue | Postgres `SELECT FOR UPDATE SKIP LOCKED` |
| Benchmarks | k6 |
| Local dev | Docker Compose |
| CI | GitHub Actions |
| Lint/format | ruff + black via pre-commit |
| Package manager | uv |

## API

| Method | Path | Notes |
|---|---|---|
| `POST` | `/v1/inference` | Single synchronous inference |
| `GET`  | `/healthz` | Liveness |
| `GET`  | `/readyz` | Readiness — vLLM reachable + DB connected |
| `GET`  | `/metrics` | Prometheus scrape |
| `POST` | `/v1/batch/jobs` | Submit a batch job |
| `GET`  | `/v1/batch/jobs` | List jobs |
| `GET`  | `/v1/batch/jobs/{id}` | Job detail with progress |
| `GET`  | `/v1/batch/jobs/{id}/items` | Paginated item list |
| `GET`  | `/v1/models` | List active model configs |
| `GET`  | `/v1/models/{name}` | Specific config |

The inference request takes `prompt`, `max_tokens`, and `temperature`. The platform serves the model defined by the active config — there is no per-request model override and no caller-supplied metadata field, by design.

## Project layout

```
ai-inference-platform/
├── docker/                # Dockerfiles for gateway and worker
├── alembic/               # Migrations
├── src/aiinfra/           # Single package, two process entrypoints
│   ├── gateway/           #   FastAPI app
│   ├── worker/            #   Background loop
│   ├── db/                #   Engine, session, models
│   ├── schemas/           #   Pydantic request/response shapes
│   ├── vllm/              #   httpx client
│   └── observability/     #   Correlation IDs + Prometheus metrics
├── tests/                 # pytest — unit and integration
├── benchmarks/            # k6 scripts and results
├── observability/         # Prometheus config + Grafana dashboards
└── docs/                  # Architecture doc and diagrams
```

Gateway and worker share a single package with two process entrypoints. They run as separate containers but share DB access, config, the vLLM client, schemas, and observability primitives.

## Design choices

- **Single-model serving via vLLM, not multi-provider routing.** The focus is the inference layer, not provider abstraction.
- **Stateless live requests.** Conversation memory and orchestration belong to the calling application.
- **Postgres `SELECT FOR UPDATE SKIP LOCKED` for the worker queue.** Adding Redis would be infrastructure for its own sake at this scale.
- **Correlation IDs in structured logs over OpenTelemetry.** Sufficient observability without the operational weight.
- **Docker Compose as the reference environment.** Kubernetes is deployment surface, not project scope.

## License

MIT — see [LICENSE](LICENSE).
