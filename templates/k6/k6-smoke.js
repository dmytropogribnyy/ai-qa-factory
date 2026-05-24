import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: 2,
  duration: '30s',
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<1000'],
  },
};

export default function () {
  const baseUrl = __ENV.BASE_URL || 'https://example.com';
  const res = http.get(baseUrl);
  check(res, { 'status is 2xx/3xx': (r) => r.status >= 200 && r.status < 400 });
  sleep(1);
}
