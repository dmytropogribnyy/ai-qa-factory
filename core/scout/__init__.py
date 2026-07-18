"""ARK Prospect QA Scout — bounded, read-only, local QA runtime (Phase 8.3).

A genuinely runnable local application that runs a bounded, read-only QA vertical over a
small set of explicit public seed URLs, reusing the existing evidence/report/state/safety
components. It never submits forms, logs in, sends outreach, solves CAPTCHAs, evades access
controls, or performs any external side effect. See docs/PHASE_CONTRACTS.md (Phase 8.3).
"""
from __future__ import annotations

SCOUT_VERSION = "2.0.1"
SCOUT_PRODUCT_NAME = "AI QA Factory / ARK Prospect QA Scout"
