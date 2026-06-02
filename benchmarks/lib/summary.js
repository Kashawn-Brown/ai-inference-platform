// Shared end-of-run summary for all k6 scenarios.
//
// k6 calls handleSummary() once with the aggregated metrics. We turn that into
// two committed artifacts in benchmarks/results/ — a machine-readable JSON and a
// human-readable markdown table — plus a one-line console recap. Filenames are
// `<scenario>-<run_tag>`; the tag is a UTC timestamp unless RUN_TAG is set.

function pad(n) {
  return String(n).padStart(2, '0');
}

function runTag() {
  if (__ENV.RUN_TAG) return __ENV.RUN_TAG;
  const d = new Date();
  return (
    `${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}` +
    `-${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}${pad(d.getUTCSeconds())}`
  );
}

function fmt(v, digits = 2) {
  return v === undefined || v === null ? 'n/a' : Number(v).toFixed(digits);
}

function cap(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function values(data, name) {
  return data.metrics[name] ? data.metrics[name].values : {};
}

// meta: { scenario, target, load, generation: { max_tokens, temperature } }
export function buildSummary(meta, data) {
  const tag = runTag();
  const base = `results/${meta.scenario}-${tag}`;

  const reqs = values(data, 'http_reqs');
  const dur = values(data, 'http_req_duration');
  const failed = values(data, 'http_req_failed');
  const checks = values(data, 'checks');
  const iters = values(data, 'iterations');

  const result = {
    scenario: meta.scenario,
    run_tag: tag,
    target: meta.target,
    load: meta.load,
    generation: meta.generation,
    metrics: {
      requests: reqs.count,
      throughput_rps: reqs.rate,
      iterations: iters.count,
      failure_rate: failed.rate,
      checks_rate: checks.rate,
      latency_ms: {
        avg: dur.avg,
        min: dur.min,
        p50: dur.med,
        p90: dur['p(90)'],
        p95: dur['p(95)'],
        p99: dur['p(99)'],
        max: dur.max,
      },
    },
  };

  const md = renderMarkdown(meta, tag, result.metrics, checks);
  const recap =
    `\n${meta.scenario}: ${fmt(reqs.count, 0)} reqs @ ${fmt(reqs.rate)}/s, ` +
    `fail ${fmt((failed.rate || 0) * 100)}%, ` +
    `p95 ${fmt(dur['p(95)'])}ms, p99 ${fmt(dur['p(99)'])}ms\n` +
    `-> ${base}.json\n-> ${base}.md\n`;

  return {
    [`${base}.json`]: JSON.stringify(result, null, 2),
    [`${base}.md`]: md,
    stdout: recap,
  };
}

function renderMarkdown(meta, tag, m, checks) {
  const lat = m.latency_ms;
  const total = (checks.passes || 0) + (checks.fails || 0);
  return [
    `# ${cap(meta.scenario)} benchmark — ${tag}`,
    '',
    `- **Scenario:** ${meta.scenario}`,
    `- **Target:** ${meta.target}`,
    `- **Load:** ${meta.load}`,
    `- **Generation:** max_tokens=${meta.generation.max_tokens}, ` +
      `temperature=${meta.generation.temperature}`,
    '',
    '## Results',
    '',
    '| Metric | Value |',
    '| --- | --- |',
    `| Requests | ${fmt(m.requests, 0)} |`,
    `| Throughput | ${fmt(m.throughput_rps)} req/s |`,
    `| Failure rate | ${fmt((m.failure_rate || 0) * 100)}% |`,
    `| Checks passed | ${fmt(checks.passes, 0)}/${fmt(total, 0)} ` +
      `(${fmt((m.checks_rate || 0) * 100)}%) |`,
    `| Latency avg | ${fmt(lat.avg)} ms |`,
    `| Latency p50 | ${fmt(lat.p50)} ms |`,
    `| Latency p90 | ${fmt(lat.p90)} ms |`,
    `| Latency p95 | ${fmt(lat.p95)} ms |`,
    `| Latency p99 | ${fmt(lat.p99)} ms |`,
    `| Latency max | ${fmt(lat.max)} ms |`,
    '',
  ].join('\n');
}
