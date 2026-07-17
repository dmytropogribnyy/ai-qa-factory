# Post-v2 Backlog — non-blocking enhancements

**Status:** the only place non-blocking enhancements are recorded. Items here are **deferred**;
they do **not** gate any release and must **not** become a new pre-v2 functional phase. The
remaining pre-v2 roadmap is frozen at exactly two functional phases (Final Phase I, Final Phase II)
plus a verification-only pass (see `docs/PRODUCT_VISION_2026.md`).

A confirmed **blocking** defect is fixed inside the active phase, never recorded here.

## Final Phase I — depth deferred (present + tested, but shallower than the full target)

These subsystems are implemented to a working, tested, safety-gated, load-bearing standard and are
proven by the deterministic integrated E2E and real local acceptance. Deeper polish is deferred:

- **Accessibility.** Real axe-core runs against rendered pages via Playwright; the deferred depth
  is a larger curated rule catalogue, per-rule remediation guidance, and colour-contrast imaging.
- **Performance.** An honestly-named Chrome/Playwright performance-observation layer (navigation
  timings, resource counts, largest-resource, transfer sizes). Full Lighthouse scoring, a trace
  viewer, and filmstrips are deferred; nothing here is labelled "Lighthouse".
- **Technical SEO.** Deep single-page + bounded same-host crawl signals. A larger crawl frontier,
  hreflang matrix analysis, and JS-vs-static metadata diffing at scale are deferred.
- **Business-flow QA.** Bounded public interactions + one proven reversible cart/session action
  with verified cleanup against fixtures. A wider public-interaction catalogue per profile is
  deferred.
- **Evidence.** Screenshot + annotated screenshot + sanitized excerpts + summaries. Playwright
  trace capture and short video are wired as optional/justified and default-off; broad trace/video
  capture is deferred.
- **Company/site memory (SQLite).** Transactional store with migrations, FKs/constraints,
  backup/restore, corruption fail-closed, and idempotent import of existing file runs. A larger
  migration history, online vacuum/compaction scheduling, and multi-file sharding are deferred.
- **Scheduler/queues.** Durable local queues with leases, retries, backoff, dead-letter,
  heartbeat, pause/resume/kill, crash recovery. A priority-aware fair scheduler and distributed
  workers are deferred (local, single-host only by design).
- **Dashboard.** All required sections and controls are present and read from persisted truth.
  Richer charts, filtering, and per-section deep drill-downs are deferred.

## General / future

- Full Lighthouse integration with sanitized summary extraction.
- Perceptual screenshot hashing for change detection.
- Licensed SEO/backlink/traffic dataset integration (no ranking/traffic claims without it).
- Additional real discovery provider adapters (currently adapter-ready + fixture/file-import).

_Final Phase II owns all sending, reply/opt-out history, follow-ups, CRM metrics, installer,
benchmark, and the v2.0 release — those are roadmap, not backlog._
