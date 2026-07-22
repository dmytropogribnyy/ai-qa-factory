"""Curated-list import (XLSX/CSV) for Manual Scan — a bounded, security-hardened file-parse layer.

Turns an uploaded .xlsx/.csv into canonical seed domains + display-only metadata and a disposition
against the EXISTING ``AnalyzedSiteRegistry``. It never persists the workbook, never evaluates a
formula or macro, treats every cell as untrusted text, and enforces hard ceilings (size / rows /
cols / sheets). Bare domains become ``https://<domain>`` seeds via the shared ``canonical_domain``.
Launch reuses the existing manual Scout path — this module produces seeds; it never runs a campaign.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.scout.discovery.analyzed_registry import ANALYZED, REJECTED, AnalyzedSiteRegistry
from core.scout.discovery.domain_intel import canonical_domain

# Header names (case-insensitive) that identify the seed column, in priority order.
_URL_HEADERS = ("scout seed url", "seed url", "url", "website", "domain", "seed")
_MAX_META_COLS = 12
_MAX_CELL = 200
# A STRICT domain shape on top of canonical_domain (which is lenient): labels of a-z0-9-, at least one
# dot, an alphabetic TLD >= 2. Untrusted cells (formulas, prose, junk) that canonical_domain may half-
# parse are rejected here so a curated list can never seed a bogus target.
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")


def _plausible_domain(dom: str) -> bool:
    return bool(_DOMAIN_RE.match(dom))


class CuratedImportError(ValueError):
    """Raised when an uploaded curated list is unsupported, malformed, oversized, or has no URL column."""


@dataclass
class ImportRow:
    row: int
    original: str
    canonical_domain: str
    seed_url: str
    valid: bool
    disposition: str                 # new | already_analyzed | rejected | duplicate | invalid
    metadata: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class ImportResult:
    import_id: str
    kind: str                        # xlsx | csv
    column: str                      # detected seed-column header
    rows: List[ImportRow]
    counters: Dict[str, int]

    def to_dict(self) -> Dict[str, Any]:
        return {"import_id": self.import_id, "kind": self.kind, "column": self.column,
                "rows": [r.to_dict() for r in self.rows], "counters": self.counters}


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _grid_from_csv(data: bytes, max_rows: int) -> List[List[str]]:
    text = data.decode("utf-8", errors="replace")
    grid: List[List[str]] = []
    for i, row in enumerate(csv.reader(io.StringIO(text))):
        if i > max_rows + 1:                              # header + max_rows data rows
            raise CuratedImportError(f"too many rows (limit {max_rows})")
        grid.append([("" if c is None else str(c)) for c in row])
    return grid


def _grid_from_xlsx(data: bytes, max_rows: int, max_sheets: int) -> List[List[str]]:
    try:
        import openpyxl
        # read_only + data_only: never evaluate a formula; cached values / text only.
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except CuratedImportError:
        raise
    except Exception as exc:  # noqa: BLE001 - any parse/decrypt failure is a refusal, never a crash
        raise CuratedImportError(f"unreadable or encrypted workbook: {type(exc).__name__}") from exc
    if len(wb.sheetnames) > max_sheets:
        raise CuratedImportError(f"too many sheets (limit {max_sheets})")
    ws = wb[wb.sheetnames[0]]
    grid: List[List[str]] = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i > max_rows + 1:
            raise CuratedImportError(f"too many rows (limit {max_rows})")
        grid.append([("" if c is None else str(c)) for c in row])
    return grid


def _detect_column(header: List[str]) -> int:
    norm = [h.strip().lower() for h in header]
    for name in _URL_HEADERS:                             # priority order
        if name in norm:
            return norm.index(name)
    raise CuratedImportError("no URL/Website/Domain/'Scout seed URL' column found")


def parse_curated_list(data: bytes, filename: str, *, registry: Optional[AnalyzedSiteRegistry] = None,
                       max_bytes: int = 5_000_000, max_rows: int = 500, max_cols: int = 40,
                       max_sheets: int = 5) -> ImportResult:
    """Parse an uploaded curated list into canonical seed rows. Raises CuratedImportError on any
    unsupported/malformed/oversized/ambiguous input. Never persists the file or evaluates a cell."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise CuratedImportError("empty upload")
    if len(data) > max_bytes:
        raise CuratedImportError(f"file too large (limit {max_bytes} bytes)")
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext == ".csv":
        kind, grid = "csv", _grid_from_csv(bytes(data), max_rows)
    elif ext == ".xlsx":
        kind, grid = "xlsx", _grid_from_xlsx(bytes(data), max_rows, max_sheets)
    else:
        raise CuratedImportError(f"unsupported file type {ext or '(none)'} — use .xlsx or .csv")
    if not grid:
        raise CuratedImportError("no rows in file")
    header = grid[0]
    if len(header) > max_cols:
        raise CuratedImportError(f"too many columns (limit {max_cols})")
    col = _detect_column(header)

    rows: List[ImportRow] = []
    seen: set = set()
    counters = {"total": 0, "valid_unique": 0, "invalid": 0, "dup_in_file": 0,
                "already_analyzed": 0, "rejected": 0}
    for idx, raw in enumerate(grid[1:], start=2):
        counters["total"] += 1
        original = (raw[col] if col < len(raw) else "").strip()[:_MAX_CELL]
        dom = canonical_domain(original).lower()
        meta = {header[j].strip()[:_MAX_CELL]: str(raw[j]).strip()[:_MAX_CELL]
                for j in range(min(len(header), _MAX_META_COLS)) if j != col and j < len(raw)
                and header[j].strip()}
        if not _plausible_domain(dom):                    # not a real domain -> invalid, never run
            counters["invalid"] += 1
            rows.append(ImportRow(idx, original, "", "", False, "invalid", meta))
            continue
        if dom in seen:
            counters["dup_in_file"] += 1
            rows.append(ImportRow(idx, original, dom, f"https://{dom}", False, "duplicate", meta))
            continue
        seen.add(dom)
        disposition = "new"
        if registry is not None:
            entry = registry.get(dom)
            status = getattr(entry, "analysis_status", "") if entry else ""
            if status == REJECTED:
                disposition = "rejected"
                counters["rejected"] += 1
            elif status == ANALYZED:
                disposition = "already_analyzed"
                counters["already_analyzed"] += 1
        if disposition == "new":
            counters["valid_unique"] += 1
        rows.append(ImportRow(idx, original, dom, f"https://{dom}", True, disposition, meta))

    import_id = f"imp-{_now_stamp()}-{hashlib.sha1(bytes(data)).hexdigest()[:8]}"
    return ImportResult(import_id=import_id, kind=kind, column=header[col], rows=rows, counters=counters)
