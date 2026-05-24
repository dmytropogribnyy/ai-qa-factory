from __future__ import annotations

from core.state import QAFactoryState


class PerformanceAgent:
    name = "Performance Agent"

    def run(self, state: QAFactoryState) -> QAFactoryState:
        if "Performance smoke testing" not in state.automation_scope:
            return state
        state.generated_outputs["performance/k6-smoke.js"] = """import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: 1,
  duration: '30s',
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<1000'],
  },
};

export default function () {
  const baseUrl = __ENV.BASE_URL || 'https://example.com';
  const res = http.get(baseUrl);
  check(res, { 'status is 2xx/3xx': r => r.status >= 200 && r.status < 400 });
  sleep(1);
}
"""
        state.generated_outputs["performance_notes.md"] = """# Performance Smoke Notes

This is a smoke baseline only, not a full load test.

Before running real load:
- confirm target environment;
- define expected traffic and SLAs;
- avoid production unless explicitly approved;
- monitor backend metrics if possible.
"""
        state.log(f"{self.name}: generated")
        return state
