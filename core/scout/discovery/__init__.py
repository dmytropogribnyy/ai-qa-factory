"""Prospect QA Scout — controlled discovery + commercial triage (Phase 8.4).

Extends the Scout runtime from "explicit seeds -> QA -> report" to
"campaign -> controlled discovery -> normalization -> dedup -> suppression ->
cheap eligibility -> commercial triage -> bounded promotion into the existing
Scout v1.0.1 QA engine -> report".

It reuses the Phase 8.2 domain contracts, the Scout URL safety, the static profiler,
`RunStore`, `ArtifactSafeWriter`, and the existing dashboard. It never scrapes, mass-crawls,
enriches contacts, drafts or sends outreach, or performs any external side effect. Discovery
content is untrusted data, never an instruction.
"""
from __future__ import annotations

DISCOVERY_VERSION = "8.4.0"
