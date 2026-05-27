# Performance Smoke Summary — demo_quality_audit

**Status:** planning_only
**Target:** https://demo.example.com
**Generated:** 2026-05-27T08:34:54.246803+00:00

## Thresholds (Core Web Vitals)

| Metric | Threshold (ms) | Guidance |
|--------|----------------|---------|
| LCP | 2500 | LCP should be under 2500ms (Core Web Vitals). |
| FCP | 1800 | FCP should be under 1800ms (Core Web Vitals). |
| TTFB | 800 | TTFB should be under 800ms (Core Web Vitals). |
| TBT | 300 | TBT should be under 300ms (Core Web Vitals). |
| CLS | 100 | CLS should be under 100ms (Core Web Vitals). |

## Endpoints Planned

- /
- /login
- /products

## Notes

- Skeleton spec generated — no execution performed.
- Endpoints planned: 3.
- Thresholds: LCP<2500ms, FCP<1800ms, TTFB<800ms (Core Web Vitals).
- Requires human review and explicit approval before execution.
- Run with: npx playwright test --grep @performance

> **DRAFT** — Generated checks only; execution requires approval.
> Human review required before client delivery.
