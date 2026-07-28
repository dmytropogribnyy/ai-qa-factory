"""Build a bounded, client-ready Scout evidence ZIP for one exact target.

The package is deliberately target-scoped: evidence from different prospects is never mixed.  It
contains a short human-readable summary, sanitized structured records, screenshots, and an optional
short reproduction video.  Raw page observations, headers, cookies, storage state, absolute paths,
commercial scorecards, and operator-only IDs are excluded.
"""
from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from core.orchestration.content_safety import ContentSecretScanner
from core.scout.discovery.domain_intel import canonical_domain
from core.scout.store import RunStore, StoreError
from core.atomic_io import atomic_replace

_MAX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024
_MAX_MEMBER_BYTES = 12 * 1024 * 1024
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_VIDEO_SUFFIXES = frozenset({".webm", ".mp4"})
_COVERAGE_FIELDS = (
    "coverage", "page_ceiling", "meaningful_pages_tested", "pages_skipped_noise",
    "pages_skipped_near_duplicate", "page_stop_reason", "flow_attempted",
    "flow_entry_found", "flow_step_attempted", "flow_step_succeeded", "flow_stop_reason",
)
_NETWORK_FIELDS = (
    "status", "timing_ms", "console_errors", "failed_resources", "blocked_requests",
    "axe_status", "axe_violations", "perf",
)
_REPRODUCTION_FIELDS = (
    "start_url", "action_url", "action_log", "precondition_ok", "final_url",
    "actual_status", "expected", "actual", "cleanup_ok", "reproduced",
    "reproduction_status", "video_decision", "video_ref",
)
# What a recorded interaction is allowed to tell a client: what was touched, what came of it, and
# proof the page was put back. Never the raw measurements — they are our instrumentation, not the
# client's evidence, and a clip with no account of its outcome is the thing this prevents.
_INTERACTION_FIELDS = (
    "scenario", "outcome", "reason", "url", "control_label", "action",
    "action_performed", "cleanup_ok", "steps",
)


class ClientEvidenceError(StoreError):
    """Client evidence could not be built safely."""


@dataclass(frozen=True)
class ClientEvidenceBundle:
    path: Path
    filename: str
    bytes: int
    included: int
    omitted: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9.-]+", "-", str(value or "").lower()).strip(".-")
    return (slug or "target")[:120]


# A client reads pictures, not a file count: at most three DISTINCT frames, and fewer whenever the
# analysis genuinely saw fewer distinct pages. This is a ceiling, never a quota.
_MAX_CLIENT_SCREENSHOTS = 3


def _frame_roles(pdir: Path) -> Dict[str, Dict[str, str]]:
    """Map ``file name -> {role, url}`` from the run's screenshots record, or {} when absent.

    Historical runs pre-date the record; their frames keep their file stem as the label rather than
    inventing a page role nobody measured.
    """
    try:
        raw = json.loads((pdir / "screenshots.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    frames = raw.get("frames") if isinstance(raw, dict) else None
    if not isinstance(frames, list):
        return {}
    out: Dict[str, Dict[str, str]] = {}
    for frame in frames:
        if isinstance(frame, dict) and frame.get("file"):
            out[str(frame["file"])] = {"role": str(frame.get("role") or ""),
                                       "url": str(frame.get("url") or "")}
    return out


def _unique_role(role: str, taken: Dict[str, Dict[str, str]]) -> str:
    base = _safe_slug(role) or "page"
    used = {meta.get("role") for meta in taken.values()}
    unique, suffix = base, 2
    while unique in used:
        unique, suffix = f"{base}-{suffix}", suffix + 1
    return unique


_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
         ".webm": "video/webm", ".mp4": "video/mp4", ".html": "text/html", ".json": "application/json",
         ".csv": "text/csv", ".txt": "text/plain"}


def _mime_for(name: str) -> str:
    return _MIME.get("." + name.rsplit(".", 1)[-1].lower(), "application/octet-stream")


def _build_identity() -> str:
    """Which build produced this package, so a disputed finding can be traced to the code that made it."""
    try:
        from core.build_identity import current_identity
        ident = current_identity()
        return str(ident.get("running_build") or ident.get("product_version") or "unknown")
    except Exception:      # noqa: BLE001 - never let provenance break the deliverable
        return "unknown"


def _run_execution_build(output_dir: str, run_id: str) -> str:
    """The build that PRODUCED this run, read from the run's own stamp — never today's checkout.

    A run recorded before stamping existed carries none, and says so rather than borrowing the
    packaging build, which would be the same false attribution in a quieter form.
    """
    try:
        from pathlib import Path
        from core.build_identity import stamped_build
        state = json.loads((Path(output_dir) / "scout" / str(run_id) / "state.json")
                           .read_text(encoding="utf-8"))
        return stamped_build(state.get("execution_build")) or "unknown"
    except Exception:      # noqa: BLE001 - never let provenance break the deliverable
        return "unknown"


def _finding_kind(finding: Dict[str, Any]) -> str:
    """What a client is looking at: a defect to fix, or an observation about the site.

    Reads the decision the canonical split already made and carried here. It does not decide again:
    by this point the fields that tell two findings apart have been dropped for the client's sake,
    and re-deciding over what is left merges findings that were never the same.
    """
    from core.scout.actionable import KIND_ACTIONABLE, kind_of
    return "Actionable" if kind_of(finding) == KIND_ACTIONABLE else "Informational"


def _findings_csv(findings: List[Dict[str, Any]]) -> str:
    """The finding list as a spreadsheet, because that is what a client forwards to their developer.

    Written with CRLF and a UTF-8 BOM: Excel on Windows opens a BOM-less UTF-8 CSV in the system
    codepage and turns every accented character into mojibake, which makes the package look broken
    before anyone reads a word of it.
    """
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(["Type", "Severity", "Category", "Title", "Impact", "Page", "How to reproduce",
                     "Evidence", "Confidence"])
    for finding in findings:
        writer.writerow([
            _finding_kind(finding),
            str(finding.get("severity") or ""),
            str(finding.get("category") or ""),
            str(finding.get("title") or ""),
            str(finding.get("business_impact") or ""),
            str(finding.get("url") or ""),
            " → ".join(str(step) for step in (finding.get("reproduction_steps") or [])),
            ", ".join(str(ref).rsplit("/", 1)[-1]
                      for ref in (finding.get("evidence_refs") or [])),
            str(finding.get("confidence") or ""),
        ])
    return "﻿" + buffer.getvalue()


def _readme_html(domain: str, *, findings: int, informational: int, screenshots: int, videos: int,
                 omitted: List[Dict[str, Any]], interactions: int = 0) -> str:
    """The first thing the client opens: what is in here and which file to read first."""
    dropped = "".join(
        f"<li>{html.escape(str(item.get('name') or 'a file'))} — "
        f"{html.escape(str(item.get('reason') or 'omitted'))}</li>" for item in omitted)
    dropped_block = (f"<h2>Not included</h2><ul>{dropped}</ul>" if dropped else "")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Start here — QA evidence for {html.escape(domain)}</title>
<style>
body{{font:15px/1.6 system-ui,-apple-system,Segoe UI,sans-serif;color:#172033;background:#f6f8fb;margin:0}}
main{{max-width:820px;margin:36px auto;padding:0 20px}}
.card{{background:#fff;border:1px solid #dfe5ee;border-radius:14px;padding:22px;margin:0 0 16px}}
h1{{margin:0 0 6px;font-size:26px}}h2{{font-size:17px;margin:20px 0 8px}}
code{{background:#eef2f8;padding:1px 5px;border-radius:4px}}a{{color:#1557c0}}
.muted{{color:#607086}}
</style></head><body><main>
<div class="card"><p class="muted">QA evidence package</p><h1>{html.escape(domain)}</h1>
<p>Everything here opens offline. Nothing needs to be installed and nothing connects to the
internet.</p>
<h2>Start with</h2>
<ul>
<li><a href="QA-Report.html">QA-Report.html</a> — the findings, with the screenshots that show
them.</li>
<li><a href="Findings.csv">Findings.csv</a> — the same list as a spreadsheet, for your tracker.</li>
</ul>
<h2>What is in the package</h2>
<ul>
<li><strong>{findings}</strong> actionable finding(s) — problems we suggest fixing</li>
<li><strong>{informational}</strong> informational note(s) — observations, not defects</li>
<li><strong>{screenshots}</strong> screenshot(s) in <code>Evidence/Screenshots/</code></li>
<li><strong>{videos}</strong> reproduction video(s) in <code>Evidence/Videos/</code> — a defect
being reproduced</li>
<li><strong>{interactions}</strong> recorded interaction(s) — a control being used, with
<code>Evidence/Technical/interaction.json</code> saying what each one showed. A recorded
interaction is not a defect unless the report lists one.</li>
<li>Accessibility, performance, console and network summaries in
<code>Evidence/Technical/</code></li>
<li><code>manifest.json</code> — a SHA-256 for every file, so either side can prove nothing was
altered.</li>
</ul>
<h2>How this was produced</h2>
<p>A bounded, read-only check of public pages. No form was submitted, no account was created, no
order was placed and no login was attempted. Findings describe what was observed on the pages
listed; they are not a claim that the site has no other issues.</p>
{dropped_block}
</div></main></body></html>"""


def _video_absence_note(detail: Dict[str, Any]) -> str:
    """Say WHY there is no reproduction video, so its absence never reads as missing evidence.

    A video proves one thing only: that an interaction really misbehaves. Accessibility, structural,
    console and performance findings are proved by the page itself, and attaching a clip of a page
    that merely loads would dress up evidence we do not have.
    """
    reproduction = detail.get("reproduction")
    if isinstance(reproduction, dict) and reproduction:
        # Scout judged THIS finding and recorded the verdict. Prefer it over any reasoning from the
        # run-wide policy: the decision was per-finding, so the explanation must be too.
        if reproduction.get("reproduction_status") == "not_reproduced":
            return ("No reproduction video: the interaction was replayed and did not misbehave, so "
                    "there was nothing to record.")
        if reproduction.get("video_decision"):
            return f"No reproduction video: {reproduction['video_decision']}."
    # The reason must be the one that actually applied. Saying "no broken interaction was found"
    # for a run whose video capture was switched off would be a confident answer to a question we
    # never asked. The operator surface already distinguishes these three cases; so must this.
    mode = str(detail.get("video_mode") or "")
    if mode == "off":
        return ("No reproduction video: video capture was disabled for this run "
                "(policy: off). This is a chosen setting, not a failed capture.")
    if mode == "manual":
        return ("No reproduction video: video capture is manual/opt-in for this run, so none was "
                "recorded automatically. This is a chosen setting, not a failed capture.")
    if mode == "qualified_auto":
        return ("No reproduction video: no confirmed finding is a broken interaction. A video is "
                "recorded only when an action genuinely misbehaves (a dead control, a broken flow, "
                "an error or lost state after a step). Accessibility, structure, console and "
                "performance findings are evidenced by the page capture and the technical records.")
    return ("No reproduction video was recorded for this target, and the capture policy for this "
            "run was not persisted, so the reason cannot be stated.")


def client_export_dir(output_dir: str, run_id: str) -> Path:
    """Return the confined derived-export directory for one run."""
    root = Path(output_dir).resolve() / "scout" / "_client_exports"
    run_key = f"{_safe_slug(run_id)}-{hashlib.sha256(run_id.encode('utf-8')).hexdigest()[:12]}"
    target = (root / run_key).resolve()
    if root not in target.parents:
        raise ClientEvidenceError("client export directory escapes the output root")
    return target


def _finding_lines(findings: Iterable[Dict[str, Any]]) -> List[str]:
    rows = []
    for finding in findings:
        severity = str(finding.get("severity") or "unknown").upper()
        title = " ".join(str(finding.get("title") or "Untitled finding").split())
        impact = " ".join(str(finding.get("business_impact") or "").split())
        rows.append(f"- **{severity}** — {title}" + (f"  \n  Impact: {impact}" if impact else ""))
    return rows


def _public_finding(finding: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only fields that explain the issue to a client; drop all run/operator references."""
    return {
        key: finding.get(key)
        for key in (
            "severity", "category", "title", "business_impact", "url", "confidence",
            "reproduction_steps",
            # The decision, carried through one more lossy step. Without it this projection is the
            # last place the split could still be reconstructed from — and it cannot be, because
            # `signature` is deliberately not here: it identifies our checks, not the client's site.
            "kind",
        )
        if finding.get(key) not in (None, "", [])
    }


def _project_fields(value: Any, allowed: Iterable[str]) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {key: value.get(key) for key in allowed if key in value}


def _client_trace(pdir: Path) -> Dict[str, Any]:
    """Project the redacted engine trace again so internal/future fields cannot leak by default."""
    path = (pdir / "browser_trace.json").resolve()
    if pdir not in path.parents or not path.is_file() or path.is_symlink():
        return {}
    if path.stat().st_size > _MAX_MEMBER_BYTES:
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {}
    if not isinstance(raw, dict) or raw.get("redaction_applied") is not True:
        return {}
    passes = []
    for item in list(raw.get("passes") or [])[:20]:
        if not isinstance(item, dict):
            continue
        passes.append(_project_fields(item, (
            "pass", "url", "final_url", "status", "ok", "screenshot_ref", "timing_ms",
            "console_errors", "failed_resources", "blocked_requests",
        )))
    return {
        "schema": "scout-client-browser-event-trace/v1",
        "redaction_applied": True,
        "raw_dom_stored": False,
        "raw_headers_stored": False,
        "passes": passes,
    }


def _html_summary(domain: str, detail: Dict[str, Any], *, images: List[str],
                  videos: List[str]) -> str:
    """Standalone, offline client report with relative links to packaged evidence."""
    findings = [_public_finding(f) for f in list(detail.get("findings") or [])]
    # Partitioned by the label each finding carries, never by asking the question again.
    actionable_items = [f for f in findings if _finding_kind(f) == "Actionable"]
    informational_items = [f for f in findings if _finding_kind(f) != "Actionable"]

    def _rows(items: List[Dict[str, Any]]) -> str:
        out = []
        for finding in items:
            steps = finding.get("reproduction_steps") or []
            steps_html = "<ol>" + "".join(
                f"<li>{html.escape(str(step))}</li>" for step in steps
            ) + "</ol>" if steps else "Not recorded"
            out.append(
                "<tr>"
                f"<td><span class=\"sev\">{html.escape(str(finding.get('severity') or 'unknown').upper())}</span></td>"
                f"<td><strong>{html.escape(str(finding.get('title') or 'Untitled finding'))}</strong>"
                f"<p>{html.escape(str(finding.get('business_impact') or 'Impact not recorded.'))}</p></td>"
                f"<td>{steps_html}</td>"
                "</tr>"
            )
        return "".join(out)

    # Two sections rather than one list with a column: a client reading a defect report should not
    # have to check a cell to learn whether the row is something we are saying is broken.
    rows = _rows(actionable_items)
    info_rows = _rows(informational_items)
    info_section = (
        '<section class="card"><h2>Informational observations</h2>'
        '<p class="muted">Recorded because they describe the site, not because we consider them '
        'defects. They are not counted as actionable findings.</p>'
        "<table><thead><tr><th>Severity</th><th>Observation</th><th>Where seen</th></tr></thead>"
        f"<tbody>{info_rows}</tbody></table></section>"
    ) if info_rows else ""
    # Label each frame by the page it shows. "Open screenshot 2" told the client nothing about what
    # they were about to open, and said "2" even when both links led to the same picture.
    media = "".join(
        f'<a href="{html.escape(str(img["name"]), quote=True)}" '
        f'title="{html.escape(str(img.get("url") or ""), quote=True)}">'
        f'{html.escape(str(img.get("role") or "page"))}</a>'
        for img in images
    )
    # A relative <video> element, not only a link: the point of an offline package is that the
    # recording plays where it was unpacked, without the recipient hunting for a player.
    players = "".join(
        f'<figure style="margin:0 0 12px"><video src="{html.escape(name, quote=True)}" controls '
        f'preload="metadata" style="max-width:100%;border-radius:8px"></video>'
        f'<figcaption class="muted">{html.escape(_video_caption(name, index))} &mdash; '
        f'<a href="{html.escape(name, quote=True)}">open the file directly</a></figcaption>'
        f'</figure>'
        for index, name in enumerate(videos, 1)
    )
    video_note = "" if videos else (
        f'<p class="muted">{html.escape(_video_absence_note(detail))}</p>')
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>QA Evidence — {html.escape(domain)}</title>
<style>
body{{font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif;color:#172033;margin:0;background:#f6f8fb}}
main{{max-width:980px;margin:32px auto;padding:0 20px}}header,.card{{background:#fff;border:1px solid #dfe5ee;
border-radius:14px;padding:22px;margin:0 0 16px}}h1{{margin:0 0 8px;font-size:28px}}h2{{font-size:19px}}
.muted{{color:#607086}}.metrics{{display:flex;gap:12px;flex-wrap:wrap}}.metric{{background:#eef4ff;
border-radius:10px;padding:10px 14px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:12px;
border-bottom:1px solid #e8ecf2;text-align:left;vertical-align:top}}.sev{{font-weight:700;font-size:12px}}
.links{{display:flex;gap:10px;flex-wrap:wrap}}a{{color:#1557c0}}ol{{margin:0;padding-left:20px}}
@media(max-width:700px){{table,thead,tbody,tr,th,td{{display:block}}thead{{display:none}}td{{padding:8px 0}}}}
</style></head><body><main>
<header><p class="muted">Client-ready QA evidence</p><h1>{html.escape(domain)}</h1>
<p>Completed bounded analysis of public pages. Review the package before sending.</p>
<div class="metrics"><div class="metric"><strong>{len(actionable_items)}</strong><br>actionable findings</div>
<div class="metric"><strong>{len(informational_items)}</strong><br>informational notes</div>
<div class="metric"><strong>{len(images)}</strong><br>unique screenshots</div>
<div class="metric"><strong>{len(videos)}</strong><br>recordings</div></div></header>
<section class="card"><h2>Actionable findings</h2>
<table><thead><tr><th>Severity</th><th>Issue and impact</th><th>How to reproduce</th></tr></thead>
<tbody>{rows or '<tr><td colspan="3">No actionable issue was recorded.</td></tr>'}</tbody></table>
</section>{info_section}<section class="card"><h2>Evidence files</h2>
<div class="links">{media or '<span class="muted">No visual evidence was captured.</span>'}</div>
{players}
{video_note}
<p class="muted">Each screenshot is a distinct page or state; byte-identical captures are not
packaged twice. Technical JSON is included for verification. The browser event trace is a
redacted structured record, not a native Playwright trace.zip.</p></section>
</main></body></html>"""


def _video_caption(name: str, index: int) -> str:
    """Say which kind of recording this is. A reproduction replays a confirmed finding; an
    interaction recording shows a control being used, and its outcome may be that nothing was
    wrong — calling both "reproduction" would put a claim in the client's hands that the clip
    does not support."""
    if "interaction-" in name:
        return f"Recorded interaction {index}"
    return f"Reproduction of a confirmed finding ({index})"


def _interaction_note(detail: Dict[str, Any]) -> str:
    """What the recorded interaction actually showed, in the client's words rather than ours.

    A clip of a control being used says nothing on its own. Shipping it beside a defect list, with
    no outcome, invites the reading that it IS the defect list moving.
    """
    record = detail.get("interaction")
    if not isinstance(record, dict) or not record:
        return "a control was recorded being used; see `Evidence/Technical/interaction.json`"
    reason = str(record.get("reason") or "").strip()
    control = str(record.get("control_label") or "a control").strip()
    outcome = str(record.get("outcome") or "").strip()
    if outcome == "defect":
        return f"{control}: {reason or 'the control did not do what it says'}"
    return (f"{control}: this recording is not a defect — "
            f"{reason or 'the control behaved correctly'}")


def _summary(domain: str, detail: Dict[str, Any], *, images: List[Dict[str, str]], videos: int,
             trace_available: bool, omitted: List[Dict[str, Any]], interactions: int = 0) -> str:
    findings = list(detail.get("findings") or [])
    # Partitioned by the carried decision. A local `severity != "info"` rule used to let
    # "informational", "none" and "" through as defects; re-running the canonical split here would
    # fix that and introduce the opposite error, merging findings the projection can no longer tell
    # apart. Reading the label does neither.
    actionable = [f for f in findings if _finding_kind(f) == "Actionable"]
    informational = [f for f in findings if _finding_kind(f) != "Actionable"]
    lines = [
        f"# QA Evidence Summary — {domain}",
        "",
        "This package was generated from one completed, bounded Scout analysis of public pages.",
        "It contains client-oriented evidence. Structured text is secret-scanned; screenshots and",
        "video still require human review. Raw headers, cookies, browser storage, credentials,",
        "absolute workspace paths, commercial scoring, and operator-only diagnostics are excluded.",
        "",
        "## Result",
        "",
        f"- Confirmed actionable findings: **{len(actionable)}**",
        f"- Informational notes: **{len(informational)}**",
        f"- Unique screenshots included: **{len(images)}**",
        *[f"  - `{img['name']}` — {img.get('role') or 'page'}"
          + (f" ({img['url']})" if img.get("url") else "")
          for img in images],
        f"- Reproduction videos included: **{videos}**",
        *([] if videos else [f"  - {_video_absence_note(detail)}"]),
        f"- Recorded interactions included: **{interactions}**",
        *([f"  - {_interaction_note(detail)}"] if interactions else []),
        f"- Structured browser event trace included: **{'yes' if trace_available else 'no'}**",
        "",
        "## Actionable findings",
        "",
        *(_finding_lines(actionable) or [
            "No actionable problem was recorded in this bounded analysis."
        ]),
        "",
        *(["## Informational observations",
           "",
           "Recorded because they describe the site; they are not counted as actionable findings.",
           "",
           *_finding_lines(informational),
           ""] if informational else []),
        "## Evidence notes",
        "",
        "- Each screenshot is a distinct page or state actually visited; a byte-identical capture",
        "  is never packaged twice, so the count above is evidence, not files.",
        "- `browser-event-trace.json` is a redacted structured event record, not a native",
        "  Playwright `trace.zip`.",
        "- Playwright Inspector is a live developer tool and is not a saved client artifact.",
        "- Review the package before sending it to a client, especially screenshots and video.",
    ]
    if omitted:
        lines += [
            "",
            "## Files omitted to keep the email attachment bounded",
            "",
            *[f"- {row['name']}: {row['reason']}" for row in omitted],
        ]
    return "\n".join(lines).rstrip() + "\n"


def build_client_evidence_bundle(output_dir: str, *, run_id: str, prospect_id: str,
                                 domain: str, detail: Dict[str, Any]) -> ClientEvidenceBundle:
    """Create one atomic, secret-scanned, <=20 MiB target evidence ZIP."""
    dom = canonical_domain(domain)
    if not dom:
        raise ClientEvidenceError("invalid target domain")
    if detail.get("analysis_complete") is not True:
        raise ClientEvidenceError("client evidence requires a completed analysis")
    store = RunStore(output_dir, run_id)
    RunStore._safe_component(prospect_id)
    if not store.exists():
        raise ClientEvidenceError("run not found")
    pdir = store.prospect_dir(prospect_id).resolve()
    if not pdir.is_dir() or store.root not in pdir.parents:
        raise ClientEvidenceError("target evidence directory not found")

    from core.scout.actionable import KIND_ACTIONABLE, count_kinds
    public_findings = [_public_finding(f) for f in list(detail.get("findings") or [])]
    # Counted from the labels the read model carried in, never by splitting again. Every number the
    # README, the report, the CSV, the JSON and the manifest print comes from this one tally, so a
    # field this projection drops can no longer change any of them.
    kinds = count_kinds(public_findings)
    actionable_total = kinds[KIND_ACTIONABLE]
    informational_total = len(public_findings) - actionable_total
    # Split by what a reader is looking for rather than by which artifact we happened to store it
    # in. "network-console-accessibility.json" required knowing our internals to guess what was in
    # it; a client hunting a slow page opens performance-summary.json.
    raw_network = detail.get("network") or {}
    structured: Dict[str, str] = {
        "Evidence/Technical/findings.json": json.dumps(
            {"schema": "scout-client-findings/v2", "domain": dom,
             "actionable_count": actionable_total,
             "informational_count": informational_total,
             "findings": [{**f, "kind": _finding_kind(f)} for f in public_findings]},
            indent=2, ensure_ascii=False, sort_keys=True),
        "Evidence/Technical/accessibility-summary.json": json.dumps(
            {"schema": "scout-client-accessibility/v1", "domain": dom,
             "tool": "axe-core",
             "status": str(raw_network.get("axe_status") or "not_attempted"),
             "violation_groups": list(raw_network.get("axe_violations") or [])},
            indent=2, ensure_ascii=False, sort_keys=True),
        "Evidence/Technical/performance-summary.json": json.dumps(
            {"schema": "scout-client-performance/v1", "domain": dom,
             "page_timings_ms": dict(raw_network.get("timing_ms") or {}),
             "metrics": dict(raw_network.get("perf") or {})},
            indent=2, ensure_ascii=False, sort_keys=True),
        "Evidence/Technical/network-summary.json": json.dumps(
            {"schema": "scout-client-network/v1", "domain": dom,
             "http_status": raw_network.get("status"),
             "failed_resources": list(raw_network.get("failed_resources") or []),
             "blocked_requests": list(raw_network.get("blocked_requests") or [])},
            indent=2, ensure_ascii=False, sort_keys=True),
        "Evidence/Technical/console-summary.txt": (
            "\n".join(str(line) for line in (raw_network.get("console_errors") or []))
            or "No console error was recorded for the pages checked."),
    }
    coverage = detail.get("coverage")
    if isinstance(coverage, dict):
        structured["Evidence/Technical/coverage.json"] = json.dumps(
            _project_fields(coverage, _COVERAGE_FIELDS),
            indent=2, ensure_ascii=False, sort_keys=True)
    reproduction = detail.get("reproduction")
    if isinstance(reproduction, dict) and reproduction:
        structured["Evidence/Technical/reproduction.json"] = json.dumps(
            _project_fields(reproduction, _REPRODUCTION_FIELDS),
            indent=2, ensure_ascii=False, sort_keys=True)
    # A recorded interaction ships with an account of what it showed, or it does not ship. The clip
    # alone is ambiguous by construction — the same footage backs "the control is broken" and "the
    # control worked", and only the outcome separates them.
    interaction = detail.get("interaction")
    if isinstance(interaction, dict) and interaction:
        structured["Evidence/Technical/interaction.json"] = json.dumps(
            _project_fields(interaction, _INTERACTION_FIELDS),
            indent=2, ensure_ascii=False, sort_keys=True)
    client_trace = _client_trace(pdir)
    if client_trace:
        structured["Evidence/Technical/browser-event-trace.json"] = json.dumps(
            client_trace, indent=2, ensure_ascii=False, sort_keys=True)

    binary: List[Tuple[str, Path]] = []
    omitted: List[Dict[str, Any]] = []
    video_count = 0
    # Screenshots are packaged as DISTINCT evidence, not as a file count. A frame whose bytes we
    # already ship (the verification pass re-photographing an unchanged landing page produces a
    # byte-identical file) adds a second link to the same picture and nothing else, so it is dropped
    # by digest. What survives is named for the page it shows and carries that page's URL.
    roles = _frame_roles(pdir)
    seen_digests: Dict[str, str] = {}
    image_meta: Dict[str, Dict[str, str]] = {}
    total = sum(len(text.encode("utf-8")) for text in structured.values())
    for rel in detail.get("media") or []:
        parts = [part for part in str(rel).replace("\\", "/").split("/") if part not in ("", ".")]
        try:
            path = store._confine(*parts).resolve()
        except StoreError:
            continue
        if pdir not in path.parents or not path.is_file() or path.is_symlink():
            continue
        suffix = path.suffix.lower()
        if suffix not in _IMAGE_SUFFIXES | _VIDEO_SUFFIXES:
            continue
        size = path.stat().st_size
        if size > _MAX_MEMBER_BYTES:
            omitted.append({"name": path.name, "reason": "single file exceeds 12 MiB"})
            continue
        if total + size > _MAX_UNCOMPRESSED_BYTES:
            omitted.append({"name": path.name, "reason": "20 MiB email-package limit reached"})
            continue
        if suffix in _IMAGE_SUFFIXES:
            digest = _sha256_file(path)
            if digest in seen_digests:
                omitted.append({"name": path.name,
                                "reason": f"identical to {seen_digests[digest]} (same SHA-256)"})
                continue
            if len(image_meta) >= _MAX_CLIENT_SCREENSHOTS:
                omitted.append({"name": path.name,
                                "reason": f"evidence budget of {_MAX_CLIENT_SCREENSHOTS} unique "
                                          "screenshots reached"})
                continue
            meta = roles.get(path.name) or {}
            role = _unique_role(str(meta.get("role") or path.stem), image_meta)
            name = f"Evidence/Screenshots/{role}{suffix}"
            seen_digests[digest] = f"{role}{suffix}"
            image_meta[name] = {"role": role, "url": str(meta.get("url") or "")}
        else:
            video_count += 1
            # Named for what it IS. A recorded interaction whose outcome was "the control worked"
            # packaged as "reproduction-01" tells the client a defect was reproduced, which is the
            # opposite of what the clip shows.
            kind = "interaction" if path.stem.lower().startswith("interaction") else "reproduction"
            name = f"Evidence/Videos/{kind}-{video_count:02d}{suffix}"
        binary.append((name, path))
        total += size

    trace_available = "Evidence/Technical/browser-event-trace.json" in structured
    # The attachment ceiling covers every uncompressed member, including the human summaries. If
    # they push a nearly-full package over the cap, omit the last media item and rebuild them so
    # their counts and their not-included note stay exact.
    base_structured = structured
    while True:
        image_names = [name for name, _path in binary if "/Screenshots/" in name]
        video_names = [name for name, _path in binary if "/Videos/" in name]
        # Counted apart, because they are different claims. A reproduction replays a confirmed
        # defect; a recorded interaction shows a control being used and may have proved nothing was
        # wrong. Adding them together let a package announce "1 reproduction video" over footage of
        # a control working correctly.
        repro_count = sum(1 for name in video_names if "/reproduction-" in name)
        interaction_count = len(video_names) - repro_count
        images = [{"name": name, **image_meta.get(name, {})} for name in image_names]
        summary = _summary(
            dom, detail, images=images, videos=repro_count, interactions=interaction_count,
            trace_available=trace_available, omitted=omitted)
        candidate = {
            "00-README.html": _readme_html(dom, findings=actionable_total,
                                           informational=informational_total,
                                           screenshots=len(image_names),
                                           videos=repro_count,
                                           interactions=interaction_count, omitted=omitted),
            "QA-Report.html": _html_summary(dom, detail, images=images, videos=video_names),
            "Findings.csv": _findings_csv(public_findings),
            "Evidence/Technical/scan-summary.md": summary,
            **base_structured,
        }
        package_bytes = sum(len(text.encode("utf-8")) for text in candidate.values())
        package_bytes += sum(path.stat().st_size for _name, path in binary)
        if package_bytes <= _MAX_UNCOMPRESSED_BYTES:
            structured = candidate
            break
        if not binary:
            raise ClientEvidenceError(
                "client evidence structured report exceeds the 20 MiB attachment limit")
        removed_name, removed_path = binary.pop()
        omitted.append({
            "name": removed_path.name,
            "reason": "20 MiB email-package limit reached",
        })
    scan = ContentSecretScanner().scan_all(structured)
    if not scan.clean:
        raise ClientEvidenceError(
            "client evidence blocked by content secret scan: " + ", ".join(scan.findings))

    entries: List[Dict[str, Any]] = []
    out_dir = client_export_dir(output_dir, run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Dated, and rooted in one folder. Two packages for the same client a month apart used to be the
    # same filename twice in a downloads folder, and extracting a flat ZIP scattered a dozen loose
    # files across whatever directory the client happened to be in.
    generated_at = _now()
    stamp = generated_at[:10].replace("-", "")
    root = f"{_safe_slug(dom)}-qa-evidence-{stamp}"
    filename = f"{root}.zip"
    path = out_dir / filename
    with tempfile.NamedTemporaryFile(
        prefix=f".{filename}.", suffix=".tmp", dir=out_dir, delete=False
    ) as temp_file:
        tmp = Path(temp_file.name)
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as archive:
            for name, text in structured.items():
                data = text.encode("utf-8")
                archive.writestr(f"{root}/{name}", data)
                entries.append({"path": name, "bytes": len(data), "mime": _mime_for(name),
                                "sha256": _sha256_bytes(data)})
            for name, source in binary:
                archive.write(source, f"{root}/{name}")
                meta = image_meta.get(name, {})
                entry = {
                    "path": name,
                    "bytes": source.stat().st_size,
                    "mime": _mime_for(name),
                    "sha256": _sha256_file(source),
                    # Bind each frame to the page it shows. Without it a screenshot is an image the
                    # client cannot place, and nothing records which walked page was captured.
                    "role": meta.get("role", ""),
                    "page_url": meta.get("url", ""),
                    "captured_at": datetime.fromtimestamp(
                        source.stat().st_mtime, tz=timezone.utc).isoformat(),
                }
                if source.suffix.lower() in _VIDEO_SUFFIXES:
                    # Enough for a recipient to confirm the clip they received is the clip that was
                    # recorded — and that it is a recording rather than a still frame.
                    from core.scout.media_probe import probe_video
                    probe = probe_video(source)
                    entry.update({"duration_s": probe.get("duration_s"),
                                  "width": probe.get("width"), "height": probe.get("height"),
                                  "playable": probe.get("playable")})
                entries.append(entry)
            manifest = {
                "schema": "scout-client-evidence/v2",
                # Provenance a disputed finding can be traced through: which site, which run, which
                # build. The internal prospect id is deliberately NOT here — it identifies our
                # numbering rather than the client's site, and this file leaves the building.
                "domain": dom,
                "target_id": dom,
                "run_id": run_id,
                # TWO builds, because they answer different questions and are routinely different
                # values. Re-exporting a months-old run stamps today's code on the package; printing
                # that single number beside the findings attributed them to code that never produced
                # them. `build` stays as the packaging build so an existing reader keeps working.
                "execution_build": _run_execution_build(output_dir, run_id),
                "package_build": _build_identity(),
                "build": _build_identity(),
                "generated_at": generated_at,
                "root": root,
                "client_oriented_scope": True,
                "structured_content_secret_scanned": True,
                "visual_review_required": True,
                "review_before_sending": True,
                # Building a package is not deciding it may be sent. This stays false in the
                # artifact itself so a forwarded ZIP cannot imply an approval nobody gave.
                "approved_for_client_delivery": False,
                # The same two numbers the README, the report, the CSV and the JSON print. A
                # manifest that disagrees with the pages it indexes is worse than no manifest.
                "actionable_findings": actionable_total,
                "informational_findings": informational_total,
                "findings": [{"title": f.get("title"), "severity": f.get("severity"),
                              "kind": _finding_kind(f),
                              "url": f.get("url"),
                              "evidence": [str(ref).rsplit("/", 1)[-1]
                                           for ref in (f.get("evidence_refs") or [])]}
                             for f in public_findings],
                "entries": entries,
                "omitted": omitted,
            }
            manifest_text = json.dumps(
                manifest, indent=2, ensure_ascii=False, sort_keys=True)
            findings = ContentSecretScanner().scan_text("manifest.json", manifest_text)
            if findings:
                raise ClientEvidenceError(
                    "client evidence manifest blocked by content secret scan")
            archive.writestr(f"{root}/manifest.json", manifest_text.encode("utf-8"))
        atomic_replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return ClientEvidenceBundle(
        path=path,
        filename=filename,
        bytes=path.stat().st_size,
        included=len(entries) + 1,
        omitted=len(omitted),
    )
