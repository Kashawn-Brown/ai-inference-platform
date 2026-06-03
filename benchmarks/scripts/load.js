// Load benchmark — sustained, realistic concurrent traffic.
//
// Ramps to a handful of virtual users (under vLLM's --max-num-seqs batch cap),
// holds, then ramps down. A closed model (ramping-vus): each VU waits for its
// response before firing again, so load is naturally backpressured and never
// piles requests past capacity — that overflow behaviour belongs to stress.
//
// Unlike smoke, this gates on latency: p95 must stay under the vLLM client
// timeout, otherwise the system isn't keeping up with the offered load.

import { inference, BASE_URL, MAX_TOKENS, TEMPERATURE } from '../lib/inference.js';
import { buildSummary } from '../lib/summary.js';

// 3 sustained VUs is the empirically sustainable concurrency on the reference
// 4GB Turing card — 5 tripped both gates live (decisions.md #28). Override for
// other hardware; fall back to 2 if a run still trips.
const VUS = Number(__ENV.LOAD_VUS || 3);
const RAMP_UP = __ENV.LOAD_RAMP_UP || '30s';
const HOLD = __ENV.LOAD_HOLD || '1m';
const RAMP_DOWN = __ENV.LOAD_RAMP_DOWN || '15s';

export const options = {
  scenarios: {
    load: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: RAMP_UP, target: VUS },
        { duration: HOLD, target: VUS },
        { duration: RAMP_DOWN, target: 0 },
      ],
      // Let an in-flight request finish during ramp-down rather than cutting it
      // mid-generation; responses here can take several seconds.
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    // Tied to the 30s vLLM client timeout: a request past it becomes a 504, so
    // "p95 under the timeout" is the real keeping-up SLO for this hardware.
    http_req_duration: ['p(95)<30000'],
    checks: ['rate>0.99'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

export default function () {
  inference();
}

export function handleSummary(data) {
  return buildSummary(
    {
      scenario: 'load',
      target: `${BASE_URL}/v1/inference`,
      load: `ramp 0->${VUS} over ${RAMP_UP}, hold ${VUS} for ${HOLD}, ramp->0 over ${RAMP_DOWN}`,
      generation: { max_tokens: MAX_TOKENS, temperature: TEMPERATURE },
    },
    data,
  );
}
