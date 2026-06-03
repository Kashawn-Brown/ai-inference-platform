// Stress benchmark — drive the system past its sustainable concurrency to
// characterize how it degrades, not to prove it stays healthy.
//
// An open model (ramping-arrival-rate): requests are offered at a target *rate*
// regardless of whether vLLM keeps up, so they pile past the --max-num-seqs 8
// batch window, sit until the 30s client timeout, and 504. That overload is the
// point. No latency/failure gate here — the climbing failure rate and the
// latency pinned at the timeout *are* the result. Read the time-resolved
// degradation curve from the Grafana dashboards while this runs.

import { inference, BASE_URL, MAX_TOKENS, TEMPERATURE } from '../lib/inference.js';
import { buildSummary } from '../lib/summary.js';

const PEAK_RPS = Number(__ENV.STRESS_PEAK_RPS || 3);
const STEP = __ENV.STRESS_STEP || '30s';
// Sized so k6 can sustain the offered rate when each request takes up to the
// full 30s timeout (~rate x max-latency VUs in flight). If dropped_iterations
// is non-zero in the summary, k6 VU-starved and masked the overload — raise it.
const MAX_VUS = Number(__ENV.STRESS_MAX_VUS || 100);

export const options = {
  scenarios: {
    stress: {
      executor: 'ramping-arrival-rate',
      startRate: 0,
      timeUnit: '1s',
      preAllocatedVUs: 10,
      maxVUs: MAX_VUS,
      stages: [
        { duration: STEP, target: 1 }, // approach capacity
        { duration: STEP, target: PEAK_RPS }, // push past it
        { duration: STEP, target: PEAK_RPS }, // hold in overload
        { duration: '15s', target: 0 }, // ramp down — observe recovery
      ],
    },
  },
  // No thresholds: stress is observational. Checks stay but are informational —
  // a low pass rate at peak is the result, not a failure.
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

export default function () {
  inference();
}

export function handleSummary(data) {
  return buildSummary(
    {
      scenario: 'stress',
      target: `${BASE_URL}/v1/inference`,
      load:
        `arrival-rate ramp 0->1->${PEAK_RPS} req/s (step ${STEP}), ` +
        `hold ${PEAK_RPS} for ${STEP}, ramp->0 over 15s; maxVUs ${MAX_VUS}`,
      generation: { max_tokens: MAX_TOKENS, temperature: TEMPERATURE },
    },
    data,
  );
}
