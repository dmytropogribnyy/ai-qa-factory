# QA Evidence & Retest — targeted before/after accessibility retest

One command demonstrates a real QA loop on an **owned synthetic page**:

```
.venv/Scripts/python.exe tools/run_qa_demo.py [--output-dir outputs] [--run-id demo-qa-<id>]
```

Runtime: `core/scout/qa_demo.py`. Tests: `tests/test_qa_demo.py`. See also
[LLM Output Evaluation](LLM_EVALUATION.md).

1. A local fixture server (`serve_demo_site(fixture_pages=...)`, isolated mapping, exact ephemeral
   host allowlist) serves a service-desk page with two deliberate defects: an image without `alt`
   and a search input without a label.
2. `PlaywrightBackend.observe(..., deep_qa=True)` captures it in real headless Chromium with real
   axe-core and a real PNG screenshot.
3. A **predefined** repair (image `alt` + visible `<label>`) is applied to the SAME document at the
   SAME URL, and the page is observed again.
4. `compare_retest` decides over `image-alt` and `label` only: `FIX_VERIFIED`, `RETEST_FAILED`,
   `BASELINE_NOT_REPRODUCED` or `BLOCKED`. Other axe rules are listed as out-of-scope.

Output lives in `<output-dir>/scout/<run-id>/` (existing `RunStore`): `config.json`, `state.json`,
`qa_demo_report.json`, `evidence/before.png`, `evidence/after.png` (canonical `EvidenceRecord`s with
SHA-256, internal-only), and an offline export `report/index.html` (relative links, no external
assets). The CLI exits 0 only for `FIX_VERIFIED`. `load_qa_demo` re-reads the persisted run and
re-verifies paths, hashes and the verdict without re-running.

## Fail-closed rules

- New run ids must match `^demo-qa-[a-zA-Z0-9_-]+$`; anything else is refused before any write,
  server or browser. Any existing run directory is refused — runs are never overwritten or reset.
- Runs saved before the naming change (`demo-interview-<id>`, report schema
  `interview_qa_demo/v1`) can still be loaded and verified; they are never rewritten, and new runs
  cannot be created under the old prefix.
- Missing Playwright/Chromium/axe, failed navigation, truncated content, malformed violations or a
  missing PNG ⇒ `BLOCKED`. No image or success is ever substituted.
- A damaged or inconsistent persisted run loads as `BLOCKED`.

## Limitations (non-claims)

- Targeted to two axe rules on a synthetic page; not a general audit and not WCAG conformance.
- The repair is fixture markup, not model-generated remediation.
- Integrity checks detect damage in a same-user local file store; they are not tamper-proof.
- No external target, provider, tunnel or outreach is used. The Dashboard does not show these runs yet.
