# Benchmarks

Load tests for the inference gateway, driven by [k6](https://k6.io/). They send
real requests to `POST /v1/inference` against a running stack — so the numbers
reflect the served model and the hardware it runs on, not a mock. See
[Baselines](#baselines) for the exact reference configuration.

Benchmarking is a manual, on-demand step. It needs a live gateway and a real
vLLM instance on a GPU, so it is deliberately kept out of CI. Results are saved
as artifact files and committed to the repo.

## Scenarios

Each scenario is one self-contained script in `scripts/`. They share the request
shape and result-writing logic in `lib/`.

| Scenario | Script | What it does |
| --- | --- | --- |
| Smoke | `scripts/smoke.js` | A single virtual user for ~30s. Proves the path works end to end and the harness writes results. Not a performance measurement. |
| Load | `scripts/load.js` | Ramps to a few concurrent users (under vLLM's batch capacity), holds, ramps down. Confirms latency stays bounded and failures stay near zero under sustained traffic. Gates on p95 below the client timeout. |
| Stress | `scripts/stress.js` | Offers an increasing *request rate* (open model) that pushes past sustainable capacity. Characterizes how the system degrades — failures climbing, latency saturating at the timeout. Observational: no pass/fail gate. |

## Running

Bring the stack up first — the benchmarks have nothing to hit otherwise:

```sh
make up           # gateway + vLLM + Postgres + observability
make bench-smoke  # runs scripts/smoke.js in the k6 container
make bench-load   # runs scripts/load.js in the k6 container
make bench-stress # runs scripts/stress.js in the k6 container
```

`make bench-smoke` runs k6 inside a container (the `k6` service, behind Compose's
`bench` profile) attached to the Compose network, so it reaches the gateway
directly. Nothing to install locally.

Common overrides (pass through to the container):

```sh
# A heavier smoke run pointed at a host-mapped gateway
docker compose --profile bench run --rm \
  -e VUS=2 -e DURATION=1m -e MAX_TOKENS=128 \
  k6 run /benchmarks/scripts/smoke.js
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `BASE_URL` | `http://gateway:8000` | Gateway base URL the script targets. |
| `VUS` | `1` | Virtual users (smoke). |
| `DURATION` | `30s` | Run length (smoke). |
| `LOAD_VUS` | `2` | Sustained virtual users (load). |
| `LOAD_RAMP_UP` | `30s` | Ramp-up duration (load). |
| `LOAD_HOLD` | `1m` | Hold duration at `LOAD_VUS` (load). |
| `LOAD_RAMP_DOWN` | `15s` | Ramp-down duration (load). |
| `STRESS_PEAK_RPS` | `3` | Peak offered request rate, req/s (stress). |
| `STRESS_STEP` | `30s` | Duration of each ramp/hold stage (stress). |
| `STRESS_MAX_VUS` | `100` | Max VUs k6 allocates to sustain the rate (stress). |
| `MAX_TOKENS` | `64` | Tokens generated per request. |
| `TEMPERATURE` | `0.7` | Sampling temperature. |
| `PROMPT` | a short fixed prompt | Prompt sent on every request. |
| `RUN_TAG` | UTC timestamp | Suffix for the result filenames. |

## Reading results

Each run writes two files into `results/`, named `<scenario>-<run_tag>`:

- **`.json`** — the machine-readable record: requests, throughput, failure rate,
  and latency (avg / p50 / p90 / p95 / p99 / max in milliseconds).
- **`.md`** — the same numbers as a table you can read at a glance.

A run also prints a one-line recap to the console. The key things to look at:

- **Failure rate** — should be ~0% on smoke; anything else means the stack is
  unhealthy.
- **Throughput** (requests/sec) — how much the gateway sustained.
- **Latency p95 / p99** — the tail. This is where a small GPU shows its limits.

The smoke scenario gates on a near-zero failure rate and all checks passing; it
does not gate on latency. The load scenario adds a latency SLO — p95 must stay
below the vLLM client timeout (30s), since a request past it becomes a 504
anyway, so crossing it means the system isn't keeping up with the offered load.

Stress is read differently. It has **no pass/fail gate** — it deliberately
overloads the system, so a high failure rate and latency pinned at the timeout
are the expected result, not a problem. The summary captures the overall
envelope (peak failure rate, worst-case latency, achieved vs offered
throughput); for the *time-resolved* degradation curve — error rate and latency
climbing as the offered rate rises — watch the Grafana dashboards while the run
is in progress. One number to check in the stress summary: `dropped_iterations`.
If it's non-zero, k6 ran out of VUs and couldn't offer the target rate, so the
overload was understated — raise `STRESS_MAX_VUS` and re-run.

## Baselines

Captured June 2026 on modest reference hardware. These characterize *this
platform's* behaviour on a small GPU — not the peak performance of the model or
of vLLM. Full per-run percentiles (p50/avg/min/max) live in the committed
`results/` artifacts; the headline figures are below.

**Reference configuration**

| | |
| --- | --- |
| GPU | NVIDIA GTX 1650 Ti, 4 GB VRAM (Turing, no tensor cores) |
| Served model | Qwen2.5-1.5B-Instruct (the platform's canonical model) |
| vLLM | fp16, `max-num-seqs 8`, `max-model-len 2048`, `enforce-eager`, TRITON_ATTN backend |
| Request | `max_tokens 64`, `temperature 0.7`, fixed single prompt |
| Gateway → vLLM timeout | 30 s (a request past it returns 504) |

**Results**

| Scenario | Offered load | Failure rate | p95 | p99 | Notes |
| --- | --- | --- | --- | --- | --- |
| Smoke | 1 VU, 30s | 0% | 5.6 s | 9.1 s | 12 requests (~0.4 req/s); path healthy, latency comfortable |
| Load | 2 VUs sustained | 0% | 25.1 s | 26.0 s | Within the 30 s SLO, but pressed close to it |
| Stress | up to 3 req/s offered | 91.67% | 30.0 s | 30.0 s | 132 requests sent, 55 dropped; latency pinned at the timeout |

**What the numbers say**

The sustainable ceiling on this card is roughly **2 concurrent requests, ~0.5
req/s** — far below vLLM's 8-sequence batch cap. The cap is a *scheduling*
limit; the real bottleneck is per-request decode latency (no tensor cores,
`enforce-eager`), which dominates and saturates concurrency early. The 1.5B model
on a 4 GB card also leaves little VRAM for KV cache, so concurrent requests
contend for cache space almost immediately — compounding the latency wall.

The three scenarios bracket that ceiling cleanly:

- **Below it** (smoke, 1 VU) the system is comfortable — p95 5.6 s, no failures.
- **At it** (load, 2 VUs) it still holds within SLO, but p95 jumps to 25.1 s —
  most of the 30 s budget is gone. Tuning load down to 2 was empirical: 5 VUs
  failed 14.3% and 3 VUs still failed 6.7% before 2 came back clean.
- **Past it** (stress, offered ramping to 3 req/s ≈ 6× capacity) it collapses —
  91.67% of requests time out and p95/p99 pin at the 30 s wall. Grafana's
  error-ratio panel was watched climbing through ~42% during the ramp; the
  whole-run aggregate reached 91.67% as the hold at peak drove nearly everything
  to time out. Of 132 requests sent, only ~8% succeeded.

One caveat on the stress run: `dropped_iterations` was 55, meaning k6 itself ran
out of VUs (at `maxVUs 100`) and couldn't fully sustain the peak offered rate.
The overload is therefore *understated* — the true breaking point is at least
this severe. Re-running with a higher `STRESS_MAX_VUS` would offer the full rate,
but the conclusion is already unambiguous: past ~2 concurrent, this hardware
falls over fast.

The takeaway isn't that the platform is slow — it's that it's honestly measured.
The same harness, pointed at a GPU with tensor cores and more VRAM headroom,
would move these numbers substantially; the breaking-point *shape* (clean below
capacity, graceful at it, hard collapse past it) is the platform characteristic
worth showing.
