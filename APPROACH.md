# How this was built

I used an AI coding agent to build this project. I'm writing this because that phrase covers two very different things — work you understand and directed, and work you accepted without following — and the rest of this document is the evidence for which one this was. It's an honest account of why the platform is shaped the way it is, the decisions that took real thought, a couple of things that broke and how I worked them out, and the method I used to keep all of it coherent.

## Why it exists

The platform is a self-hosted layer between an application and a model: a FastAPI gateway for live, synchronous requests, a background worker for batch jobs, vLLM serving an open-weight model underneath, and Postgres holding job state. Prometheus, Grafana, and structured logs make it observable.

I didn't build it because nothing like it exists — vLLM already does the hard part, serving the model, and I use it as-is. What I wanted to build was the operational system *around* a model that most "AI platform" projects skip: a real API surface, an asynchronous batch path with a proper queue, honest health and readiness semantics, metrics and tracing, benchmarks, and a reproducible local stack. Reaching for a hosted API would have hidden exactly the parts I wanted to build and understand. So the scope is deliberately narrow — one model, no provider routing, no orchestration framework — and the depth is in operating it well rather than in surface area.

## How I worked

I used the agent as the implementer, but the project ran against a written contract I wrote first and maintained throughout, not a stream of one-off prompts.

Before any feature work I wrote an implementation brief that locked the architecture, the API surface, the data model, and a phase-by-phase plan — and, just as importantly, an explicit out-of-scope list: no Redis, no OpenTelemetry, no RAG, no multi-tenancy, no provider routing, no conversation memory. Those fences mattered as much as the plan. AI tooling will happily say yes to "while we're at it, let's also add…", and a lot of how this stayed coherent was a standing instruction to stop and flag anything drifting toward that list rather than quietly build it.

Alongside that I kept a set of working files the repo doesn't expose: a decisions log, a running plan, a build narrative, and notes on conventions and how I wanted sessions to behave. The decisions log did the most work — every architectural choice went in with its reasoning, the alternatives I'd weighed, and the condition that would reverse it. That's what kept settled questions settled: when the same trade-off resurfaced two phases later, the answer and the why were already written down, so I wasn't re-litigating or silently contradicting an earlier call. The conventions notes pinned things like "configuration has one source of truth" and "comments explain why, not what," so the code stayed consistent no matter which session produced it.

The loop itself was deliberate: state what we're about to build and what we're explicitly *not*, agree the plan, build in small steps, and treat nothing as done until it was tested, the docs were updated, and there was a clean commit at a logical checkpoint. Work went on feature branches into a protected `main` through PRs. None of this is exotic — it's roughly how I'd want to work without an agent — but it's the difference between directing the tooling and being led by it.

## Decisions that shaped it

A handful of choices did more than the rest to shape the system. These are the ones with a real trade-off behind them, not a default.

**Postgres is the work queue — no Redis.** The worker pulls jobs with `SELECT … FOR UPDATE SKIP LOCKED`, which is a genuine concurrent queue: workers skip a row another holds instead of blocking or double-claiming it. A dedicated broker is the reflexive choice, but at this scale it's a moving part that earns nothing, and Postgres is already in the stack. I accepted the trade-off explicitly — v1 has no reaper for an item left `running` by a crashed worker — and wrote it down as the thing that flips this decision if a second worker or crash recovery ever becomes real.

**The worker calls vLLM directly, and the client is shared.** The gateway owns the live request path, the worker owns batch execution, and neither goes through the other. Both reach the model through one client that holds the timeout handling and the mapping of network failures into typed errors. The brief's wording implied a gateway-local client, but that would have duplicated that logic across two callers — so the client lives at the package level and both reuse it untouched.

**The database, not an environment variable, decides which model is served.** Two callers need one authority — the gateway stamping a job's model and the worker choosing what to run — so the active model lives in a `model_configs` row, seeded deterministically in the first migration with literal values rather than read from runtime config. (A migration that reads config produces different database state in different environments, which defeats the point of a migration.) It means serving identity can't silently change under the system because someone set an env var.

**Correlation IDs go in the logs, never in the metrics.** Every request and batch item carries an ID through a `contextvars`-backed store that stamps it onto every log line automatically, so one request is traceable across everything it logs. I deliberately kept those IDs out of Prometheus labels: a label with a unique value per request is the textbook way to blow up metric cardinality. Tracing a failure means finding it in a metric by status and time, then jumping to the log line that carries the ID and the cause. The gateway binds the ID in pure-ASGI middleware rather than the higher-level kind, because the higher-level middleware runs the route in a separate task where the contextvar wouldn't be visible — a detail that only matters once and breaks quietly if you get it wrong.

## Two things that didn't work

These two stand out because the fix in each case came from understanding *why* it broke, not from trying things until it worked.

**vLLM wouldn't start on the GPU I had.** The development machine has a GTX 1650 Ti — a Turing card with 4GB of VRAM and, crucially, no tensor cores. vLLM's default attention backend (FlashInfer) crashed at startup demanding `sm75+`; the card *reports* sm75, so the error was misleading — the real requirement is tensor cores, which this chip doesn't have. Working through vLLM's backend list: XFORMERS had been dropped in the version I was on, TORCH_SDPA was named but not actually registered in the default CUDA build (it raised "must be registered before use"), and TRITON_ATTN — Triton kernels, no tensor cores needed — was the one that booted. The flag had also moved: the old `VLLM_ATTENTION_BACKEND` environment variable was removed in a recent version and silently ignored, so it had to go through `--attention-config.backend`. The whole chain is in the decisions log precisely because it's the kind of thing I'd otherwise re-discover from scratch in six months.

**A migration that ran successfully and changed nothing.** Early in the batch phase, the first migration reported success but created no tables. The cause wasn't the migration — it was that the gateway and worker containers had their source baked in at build time, so the freshly written migration file didn't exist inside the running container, and `alembic upgrade head` was upgrading against zero revision scripts. The project installs editable, with the source on the container's path, so the fix was a committed Compose override that bind-mounts the live source and migrations into the containers for local development, while the production image definitions stay faithful to how they'd actually ship. That one bug fixed the entire local development loop, not just migrations — after it, source edits took effect without a rebuild.

## Keeping it maintainable

The thing I was most deliberate about was that adding each phase didn't quietly degrade the last one.

Some of that is ordinary discipline: every change runs the same gate before it can merge — lint, format, the full test suite, and a from-scratch container build — and `main` is protected so nothing skips it. The integration tests run against a real throwaway Postgres rather than a mock, because the endpoints lean on Postgres-specific behavior (JSONB, UUIDs, keyset pagination) that a stand-in would paper over; I'd rather the tests exercise the real thing.

The less obvious part is structural. Shared seams — the vLLM client, the metrics module — were built once and reused, so when the worker needed metrics it published through the same module the gateway already used instead of growing a parallel copy. The decisions log meant consistency didn't depend on memory, and the scope fences meant the surface didn't sprawl. The final phase included a deliberate read-through of the whole codebase looking specifically for dead code, drift, and stale comments — and the fact that it turned up only cosmetic things, plus one latent rough edge I chose to flag rather than silently change, is the actual evidence the discipline held rather than a claim that it did.

## In short

The result is a small system, on purpose. But there isn't a part of it I can't explain or change — which was the whole point. The agent made it faster to build, not less mine.
