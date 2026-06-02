# Benchmarks

Load tests for the inference gateway, driven by [k6](https://k6.io/). They send
real requests to `POST /v1/inference` against a running stack — so the numbers
reflect the model (Qwen2.5-1.5B-Instruct on vLLM) and the hardware it runs on,
not a mock.

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

The stress scenario is added later in this phase.

## Running

Bring the stack up first — the benchmarks have nothing to hit otherwise:

```sh
make up          # gateway + vLLM + Postgres + observability
make bench-smoke # runs scripts/smoke.js in the k6 container
make bench-load  # runs scripts/load.js in the k6 container
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
| `LOAD_VUS` | `5` | Sustained virtual users (load). |
| `LOAD_RAMP_UP` | `30s` | Ramp-up duration (load). |
| `LOAD_HOLD` | `1m` | Hold duration at `LOAD_VUS` (load). |
| `LOAD_RAMP_DOWN` | `15s` | Ramp-down duration (load). |
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

## Baselines

Documented baseline numbers for the reference hardware land here once all three
scenarios are in and have been run.
