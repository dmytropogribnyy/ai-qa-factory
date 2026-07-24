"""Build a bounded, client-ready Scout evidence ZIP for one exact target.

The package is deliberately target-scoped: evidence from different prospects is never mixed.  It
contains a short human-readable summary, sanitized structured records, screenshots, and an optional
short reproduction video.  Raw page observations, headers, cookies, storage state, absolute paths,
commercial scorecards, and operator-only IDs are excluded.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
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
    "reproduction_status", "video_ref",
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
    rows = []
    for finding in findings:
        steps = finding.get("reproduction_steps") or []
        steps_html = "<ol>" + "".join(
            f"<li>{html.escape(str(step))}</li>" for step in steps
        ) + "</ol>" if steps else "Not recorded"
        rows.append(
            "<tr>"
            f"<td><span class=\"sev\">{html.escape(str(finding.get('severity') or 'unknown').upper())}</span></td>"
            f"<td><strong>{html.escape(str(finding.get('title') or 'Untitled finding'))}</strong>"
            f"<p>{html.escape(str(finding.get('business_impact') or 'Impact not recorded.'))}</p></td>"
            f"<td>{steps_html}</td>"
            "</tr>"
        )
    media = "".join(
        f'<a href="{html.escape(name, quote=True)}">Open screenshot {index}</a>'
        for index, name in enumerate(images, 1)
    )
    media += "".join(
        f'<a href="{html.escape(name, quote=True)}">Open reproduction video {index}</a>'
        for index, name in enumerate(videos, 1)
    )
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
<div class="metrics"><div class="metric"><strong>{len(findings)}</strong><br>confirmed findings</div>
<div class="metric"><strong>{len(images)}</strong><br>screenshots</div>
<div class="metric"><strong>{len(videos)}</strong><br>reproduction videos</div></div></header>
<section class="card"><h2>Findings</h2>
<table><thead><tr><th>Severity</th><th>Issue and impact</th><th>How to reproduce</th></tr></thead>
<tbody>{''.join(rows) or '<tr><td colspan="3">No confirmed issue was recorded.</td></tr>'}</tbody></table>
</section><section class="card"><h2>Evidence files</h2>
<div class="links">{media or '<span class="muted">No visual evidence was captured.</span>'}</div>
<p class="muted">Technical JSON is included for verification. The browser event trace is a
redacted structured record, not a native Playwright trace.zip.</p></section>
</main></body></html>"""


def _summary(domain: str, detail: Dict[str, Any], *, images: int, videos: int,
             trace_available: bool, omitted: List[Dict[str, Any]]) -> str:
    findings = list(detail.get("findings") or [])
    actionable = [f for f in findings
                  if str(f.get("severity") or "").strip().lower() != "info"]
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
        f"- Informational notes: **{len(findings) - len(actionable)}**",
        f"- Screenshots included: **{images}**",
        f"- Reproduction videos included: **{videos}**",
        f"- Structured browser event trace included: **{'yes' if trace_available else 'no'}**",
        "",
        "## Findings",
        "",
        *(_finding_lines(findings) or [
            "No confirmed problem items were recorded in this bounded analysis."
        ]),
        "",
        "## Evidence notes",
        "",
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

    public_findings = [_public_finding(f) for f in list(detail.get("findings") or [])]
    structured: Dict[str, str] = {
        "technical/findings.json": json.dumps(
            {"schema": "scout-client-findings/v1", "domain": dom,
             "findings": public_findings},
            indent=2, ensure_ascii=False, sort_keys=True),
    }
    coverage = detail.get("coverage")
    if isinstance(coverage, dict):
        structured["technical/coverage.json"] = json.dumps(
            _project_fields(coverage, _COVERAGE_FIELDS),
            indent=2, ensure_ascii=False, sort_keys=True)
    network = _project_fields(detail.get("network"), _NETWORK_FIELDS)
    if network:
        structured["technical/network-console-accessibility.json"] = json.dumps(
            network, indent=2, ensure_ascii=False, sort_keys=True)
    reproduction = detail.get("reproduction")
    if isinstance(reproduction, dict) and reproduction:
        structured["technical/reproduction.json"] = json.dumps(
            _project_fields(reproduction, _REPRODUCTION_FIELDS),
            indent=2, ensure_ascii=False, sort_keys=True)
    client_trace = _client_trace(pdir)
    if client_trace:
        structured["technical/browser-event-trace.json"] = json.dumps(
            client_trace, indent=2, ensure_ascii=False, sort_keys=True)

    binary: List[Tuple[str, Path]] = []
    omitted: List[Dict[str, Any]] = []
    image_count = video_count = 0
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
            image_count += 1
            name = f"evidence/screenshots/screenshot-{image_count:02d}{suffix}"
        else:
            video_count += 1
            name = f"evidence/reproduction/reproduction-{video_count:02d}{suffix}"
        binary.append((name, path))
        total += size

    trace_available = "technical/browser-event-trace.json" in structured
    # The attachment ceiling covers every uncompressed member, including both human summaries.
    # If summaries push a nearly-full package over the cap, omit the last media item and rebuild the
    # summaries so their counts and omitted-file note remain exact.
    base_structured = structured
    while True:
        image_names = [name for name, _path in binary if "/screenshots/" in name]
        video_names = [name for name, _path in binary if "/reproduction/" in name]
        summary = _summary(
            dom, detail, images=len(image_names), videos=len(video_names),
            trace_available=trace_available, omitted=omitted)
        html_summary = _html_summary(
            dom, detail, images=image_names, videos=video_names)
        candidate = {
            "QA_Evidence_Summary.html": html_summary,
            "QA_Evidence_Summary.md": summary,
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
    filename = f"{_safe_slug(dom)}-qa-evidence.zip"
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
                archive.writestr(name, data)
                entries.append({"path": name, "bytes": len(data), "sha256": _sha256_bytes(data)})
            for name, source in binary:
                archive.write(source, name)
                entries.append({
                    "path": name,
                    "bytes": source.stat().st_size,
                    "sha256": _sha256_file(source),
                })
            manifest = {
                "schema": "scout-client-evidence/v1",
                "domain": dom,
                "generated_at": _now(),
                "client_oriented_scope": True,
                "structured_content_secret_scanned": True,
                "visual_review_required": True,
                "review_before_sending": True,
                "entries": entries,
                "omitted": omitted,
            }
            manifest_text = json.dumps(
                manifest, indent=2, ensure_ascii=False, sort_keys=True)
            findings = ContentSecretScanner().scan_text("MANIFEST.json", manifest_text)
            if findings:
                raise ClientEvidenceError(
                    "client evidence manifest blocked by content secret scan")
            archive.writestr("MANIFEST.json", manifest_text.encode("utf-8"))
        os.replace(tmp, path)
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
