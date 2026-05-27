# QA Evidence Report — demo-client-delivery

**Generated:** 2026-05-27 14:00 UTC
**Project:** demo-client-delivery
**Tool:** AI QA Factory v5.9.0

## Test Execution Summary

| Category | Run | Passed | Failed | Skipped |
|----------|-----|--------|--------|---------|
| Browser smoke (desktop) | 12 | 12 | 0 | 0 |
| Browser smoke (mobile) | 4 | 4 | 0 | 0 |
| API smoke (safe_readonly) | 7 | 7 | 0 | 0 |
| Auth smoke (test account) | 2 | 2 | 0 | 0 |
| Visual regression | 6 | 6 | 0 | 0 |
| **Total** | **31** | **31** | **0** | **0** |

## Warnings Identified

- Homepage load time: 2.8s (above 2.5s guidance threshold — not a blocker)
- Product listing returned 304 Not Modified on second request (acceptable caching)
- Mobile nav menu: tap target slightly small on 320px width (low severity)

## Not Tested

- Checkout and payment flows (blocked_by_default)
- Admin panel endpoints (blocked_by_default)
- DELETE operations (blocked_by_default — always)
- Performance load testing (out of scope)

## Coverage Areas

- Homepage, product listing, search, category browsing
- API health, products list, product detail, categories
- Login/logout (test account), session handling
- Mobile viewport (375px, 768px), desktop (1280px, 1920px)
- Visual regression baseline established (6 reference screenshots)

## Evidence Artifacts

- Screenshots: `14_qa_report/screenshots/` (12 files, retention: on-failure only)
- Traces: `14_qa_report/traces/` (0 collected — all tests passed)
- HTML report: `14_qa_report/playwright-report/index.html`
