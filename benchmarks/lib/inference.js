// Shared inference request for all k6 scenarios.
//
// One POST to the gateway's /v1/inference plus the checks every scenario cares
// about (right status, non-empty output, a request_id echoed back). Scenarios
// (smoke/load/stress) drive load; this owns the per-request shape so the body
// and assertions stay identical across them.

import http from 'k6/http';
import { check } from 'k6';

export const BASE_URL = __ENV.BASE_URL || 'http://gateway:8000';
export const ENDPOINT = `${BASE_URL}/v1/inference`;

// Generation params are env-overridable so a run can be re-pointed without
// editing the script. Small max_tokens by default: keeps per-request work
// bounded and throughput numbers comparable across runs.
export const MAX_TOKENS = Number(__ENV.MAX_TOKENS || 64);
export const TEMPERATURE = Number(__ENV.TEMPERATURE || 0.7);
export const PROMPT =
  __ENV.PROMPT || 'In one sentence, explain what a load test measures.';

export function inference() {
  const payload = JSON.stringify({
    prompt: PROMPT,
    max_tokens: MAX_TOKENS,
    temperature: TEMPERATURE,
  });

  const res = http.post(ENDPOINT, payload, {
    headers: { 'Content-Type': 'application/json' },
  });

  check(res, {
    'status is 200': (r) => r.status === 200,
    'has output': (r) => {
      try {
        return (r.json('output') || '').length > 0;
      } catch (_) {
        return false;
      }
    },
    'has request_id': (r) => {
      try {
        return !!r.json('request_id');
      } catch (_) {
        return false;
      }
    },
  });

  return res;
}
