// Smoke benchmark — the lightest scenario.
//
// A single virtual user hitting POST /v1/inference for a short window. The point
// is not to measure performance but to prove the whole path works end to end
// (k6 -> gateway -> vLLM) and that the harness writes its result artifacts. If
// this fails, load/stress aren't worth running.

import { inference, BASE_URL, MAX_TOKENS, TEMPERATURE } from '../lib/inference.js';
import { buildSummary } from '../lib/summary.js';

const VUS = Number(__ENV.VUS || 1);
const DURATION = __ENV.DURATION || '30s';

export const options = {
  scenarios: {
    smoke: {
      executor: 'constant-vus',
      vus: VUS,
      duration: DURATION,
    },
  },
  // Smoke must be clean: effectively no failures, all checks passing. Latency
  // is recorded for the baseline but not gated here — load/stress own SLOs.
  thresholds: {
    http_req_failed: ['rate<0.01'],
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
      scenario: 'smoke',
      target: `${BASE_URL}/v1/inference`,
      load: `${VUS} VU for ${DURATION}`,
      generation: { max_tokens: MAX_TOKENS, temperature: TEMPERATURE },
    },
    data,
  );
}
