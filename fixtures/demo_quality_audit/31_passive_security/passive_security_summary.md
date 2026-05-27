# Passive Security Summary — demo_quality_audit

**Status:** executed
**Target:** https://demo.example.com
**Generated:** 2026-05-27T10:00:00+00:00

## Security Header Results

| Header | Status | Guidance |
|--------|--------|---------|
| strict-transport-security | ✓ present | Enforce HTTPS; max-age >= 15552000 (6 months). |
| content-security-policy | ✗ missing | Define allowed sources to mitigate XSS. |
| x-content-type-options | ✓ present | Should be 'nosniff' to prevent MIME sniffing. |
| x-frame-options | ✓ present | Should be 'DENY' or 'SAMEORIGIN' to prevent clickjacking. |
| referrer-policy | ✗ missing | Should be 'strict-origin-when-cross-origin' or stricter. |

## Notes

- HEAD request performed against https://demo.example.com.
- Headers present: 3/5.
- Headers missing: ['content-security-policy', 'referrer-policy']
- Human review required before client delivery.

> **Executed** — 5 headers checked, 2 missing.
> Human review required before client delivery.
