"""M5 — an unscanned file may not reach DELIVERY_PREPARED inside a package recorded as scanned.

`prepare_delivery` is documented (`work_execution.py:393`) as secret-scanning "the exact delivery file
set". `_scan_delivery` scanned a subset: it did `continue` on any file over 2 MB and on anything that
failed strict UTF-8, returning no signal either way. An empty result reads as "clean", so the manifest
was written with `approved_for_delivery: True` and the run advanced to DELIVERY_PREPARED with a file
nobody had read.

A 2 550 042-byte text artifact already exists in a real delivery workspace on this machine, but the
case does not rest on it: the skip is unconditional on size and the function had no way to report what
it declined to read. Absence of a large file would not have exonerated the code — the M3 lesson.

Everything here drives the real `WorkExecutionService` lifecycle and reads the persisted result. All
fixtures are built inside the pytest temp workspace; the existing real workspace file is evidence
only and is never touched.
"""
from __future__ import annotations

import builtins
import json
import sys
from pathlib import Path

import pytest

from core.orchestration.claude_worker import ClaudeWorkerExecutor, FixtureClaudeWorker
from core.orchestration.client_work import ClientWorkService
from core.orchestration.operator_executor import CommandValidationExecutor
from core.orchestration.providers import FixedClock, SequentialIds
from core.orchestration.work_execution import WorkExecutionError, WorkExecutionService

_BRIEF = "Prepare a delivery package whose contents must be provably scanned before sealing."
_VALIDATION_ARGV = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_pkg.py"]

# A real pattern from the production scanner (`stripe_secret_key`), not an invented marker.
SECRET = "sk_live_" + "A" * 24
# Filler chosen to contain no secret-like construct of its own: no `pass:`/`pass=`, no token shapes.
_FILLER_LINE = "the quick brown fox jumps over the lazy dog 0123456789\n"
_OLD_CAP = 2_000_000

# The seam test must not import the implementation's chunk size — this file has to collect and fail
# on the pre-fix tree, where no such constant exists. Instead each plausible chunk size is exercised
# as its own case, so whichever one the implementation picks is genuinely covered by a straddling
# secret rather than by a secret that happens to sit mid-chunk.
_CHUNK_CANDIDATES = (64 * 1024, 256 * 1024, 1024 * 1024)


def _filler(size: int) -> str:
    reps = size // len(_FILLER_LINE) + 1
    return (_FILLER_LINE * reps)[:size]


def _text_over_cap(secret_at: int | None = None) -> str:
    """A text artifact larger than the old 2 MB cap, optionally with a secret at a byte offset."""
    total = _OLD_CAP + 550_000
    if secret_at is None:
        return _filler(total)
    # The secret must start on a word boundary: every pattern is `\b`-anchored, and butting it
    # against a filler digit produces a file with no detectable secret in it — a test that asserts
    # a block while giving the scanner nothing to find.
    head = _filler(secret_at - 1) + "\n"
    return head + SECRET + _filler(total - len(head) - len(SECRET))


def _ready_for_delivery(tmp_path: Path, pid: str, members: dict[str, bytes]):
    """Drive the real lifecycle to READY_FOR_DELIVERY with `members` registered in the package.

    The worker writes each member as a placeholder so it is registered as a produced artifact; the
    real bytes are written before validation, so the validated snapshot — and therefore the sealed
    manifest — covers exactly the bytes under test. Binary members must be written this way because
    the fixture worker writes text.
    """
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(_BRIEF, pid)
    ws = tmp_path / pid / "40_ark_work"
    (ws / "test_pkg.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    svc = WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))
    svc.approve(pid, reviewer="op")
    svc.execute(pid, ClaudeWorkerExecutor(FixtureClaudeWorker(
        edits={rel: "placeholder\n" for rel in members})))
    for rel, blob in members.items():
        # write_bytes, never write_text: on Windows write_text silently turns LF into CRLF, which
        # would move every byte offset this file depends on.
        (ws / rel).write_bytes(blob)

    state, res = svc.validate(pid, CommandValidationExecutor(_VALIDATION_ARGV))
    assert res.passed and state.status == "READY_FOR_REVIEW", "fixture failed before the assertion"
    svc.review(pid, reviewer="op", approved=True)
    return svc, ws


def _seal_absent(ws: Path) -> None:
    """A refused delivery must leave nothing sealed behind."""
    for name in ("WORK_DELIVERY_MANIFEST.json", "DELIVERY_PREPARED.json"):
        assert not (ws / name).exists(), (
            f"{name} was written for a delivery that was refused; a success artifact must not "
            "record a failure"
        )


def _dispositions(manifest: dict) -> dict:
    """Per-file content-scan disposition recorded in the successful manifest."""
    cov = manifest.get("content_scan") or {}
    return {entry.get("path"): entry for entry in (cov.get("files") or [])}


# --- the fixtures must be what they claim to be -------------------------------------------------

def test_the_fixture_really_contains_a_secret_the_production_scanner_finds():
    """Guards every block assertion below from passing on an empty promise.

    An earlier draft of this file butted the secret against a filler digit, which defeats the `\\b`
    anchor: the tests demanded a refusal while handing the scanner nothing to refuse. This pins the
    fixture against the real scanner, so that failure mode cannot come back unnoticed.
    """
    from core.orchestration.content_safety import ContentSecretScanner

    assert ContentSecretScanner().scan_text("big.txt", _text_over_cap(secret_at=_OLD_CAP + 100)), (
        "the oversized fixture contains no secret the production scanner recognises"
    )
    assert not ContentSecretScanner().scan_text("big.txt", _text_over_cap()), (
        "the clean fixture trips the scanner, so the success cases prove nothing"
    )


# --- what the client is promised -------------------------------------------------------------

def test_clean_text_above_the_old_cap_is_scanned_and_delivered(tmp_path):
    """The former cap silently skipped this file. It must now be read, and said to have been read."""
    svc, ws = _ready_for_delivery(tmp_path, "clean", {"big.txt": _text_over_cap().encode("utf-8")})
    manifest = svc.prepare_delivery("clean")

    assert svc.status("clean").status == "DELIVERY_PREPARED"
    disp = _dispositions(manifest)
    assert "big.txt" in disp, (
        "the manifest records no content-scan disposition for a 2.5 MB text member, so the package "
        f"cannot say whether it was read: {sorted(disp)}"
    )
    assert disp["big.txt"].get("disposition") == "scanned_text", disp["big.txt"]


def test_a_secret_in_a_large_text_file_blocks_delivery(tmp_path):
    """The blocker itself: over the old cap, so the secret was never looked at."""
    svc, ws = _ready_for_delivery(
        tmp_path, "leak", {"big.txt": _text_over_cap(secret_at=_OLD_CAP + 100).encode("utf-8")})

    with pytest.raises(WorkExecutionError) as exc:
        svc.prepare_delivery("leak")
    assert "big.txt" in str(exc.value), f"the refusal does not name the file: {exc.value}"
    assert svc.status("leak").status == "READY_FOR_DELIVERY"
    _seal_absent(ws)


@pytest.mark.parametrize("boundary", _CHUNK_CANDIDATES)
def test_a_secret_straddling_the_streaming_seam_blocks_delivery(tmp_path, boundary):
    """A secret split across the read boundary must still be found, not lost between chunks."""
    at = boundary - len(SECRET) // 2
    svc, ws = _ready_for_delivery(
        tmp_path, f"seam{boundary}", {"big.txt": _text_over_cap(secret_at=at).encode("utf-8")})

    with pytest.raises(WorkExecutionError) as exc:
        svc.prepare_delivery(f"seam{boundary}")
    assert "big.txt" in str(exc.value)
    _seal_absent(ws)


def test_a_multibyte_character_split_across_chunks_stays_clean(tmp_path):
    """Valid UTF-8 must not be mistaken for undecodable because a character crossed a read boundary.

    Without incremental decoding this file fails closed — a false refusal, which is its own defect:
    it would make ordinary non-English deliverables undeliverable.
    """
    # A 3-byte character positioned so its bytes span each candidate boundary.
    blob = bytearray(_filler(_OLD_CAP + 550_000).encode("utf-8"))
    for boundary in _CHUNK_CANDIDATES:
        blob[boundary - 1:boundary + 2] = "ю".encode("utf-8")
    svc, _ = _ready_for_delivery(tmp_path, "mb", {"big.txt": bytes(blob)})

    manifest = svc.prepare_delivery("mb")
    assert svc.status("mb").status == "DELIVERY_PREPARED"
    assert _dispositions(manifest)["big.txt"].get("disposition") == "scanned_text"


# --- what may not pass as an allowed limitation ------------------------------------------------

def test_invalid_utf8_fails_closed(tmp_path):
    """One corrupt byte must not turn an arbitrary artifact into an allowed binary limitation."""
    blob = _filler(4096).encode("utf-8") + b"\xff\xfe" + SECRET.encode("utf-8")
    svc, ws = _ready_for_delivery(tmp_path, "badutf", {"notes.txt": blob})

    with pytest.raises(WorkExecutionError) as exc:
        svc.prepare_delivery("badutf")
    assert "notes.txt" in str(exc.value), f"the refusal does not name the file: {exc.value}"
    assert svc.status("badutf").status == "READY_FOR_DELIVERY"
    _seal_absent(ws)


def test_unknown_binary_fails_closed(tmp_path):
    """Bytes of no recognised evidence type are unknown, and unknown fails closed."""
    svc, ws = _ready_for_delivery(tmp_path, "unknown", {"blob.bin": bytes(range(256)) * 8})

    with pytest.raises(WorkExecutionError) as exc:
        svc.prepare_delivery("unknown")
    assert "blob.bin" in str(exc.value)
    _seal_absent(ws)


def test_a_verified_binary_evidence_is_named_in_the_successful_manifest(tmp_path):
    """A real PNG is an allowed limitation — but only when recorded explicitly, per path."""
    png = b"\x89PNG\r\n\x1a\n" + bytes(512)
    svc, _ = _ready_for_delivery(tmp_path, "png", {"evidence/shot.png": png})

    manifest = svc.prepare_delivery("png")
    assert svc.status("png").status == "DELIVERY_PREPARED"
    entry = _dispositions(manifest).get("evidence/shot.png")
    assert entry, "an allowed binary is not named in the manifest, so its limitation is implied only"
    assert entry.get("disposition") == "verified_binary"
    assert entry.get("type"), f"the allowed binary records no verified type: {entry}"


def test_a_read_error_fails_closed(tmp_path):
    """An unreadable member is not a clean member.

    Guard, not part of the red proof: it already passes on the unfixed tree, where the failure comes
    from the hasher rather than the scanner. It is kept because after the fix the scan and the hash
    read the same stream, so this pins that an injected read error still refuses rather than
    degrading into "nothing to scan".
    """
    svc, ws = _ready_for_delivery(tmp_path, "ioerr", {"big.txt": _text_over_cap().encode("utf-8")})
    real_open = builtins.open

    def _boom(file, *a, **kw):
        if str(file).endswith("big.txt") and "b" in str(kw.get("mode", a[0] if a else "r")):
            raise OSError("injected read failure")
        return real_open(file, *a, **kw)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(builtins, "open", _boom)
        with pytest.raises((WorkExecutionError, OSError)):
            svc.prepare_delivery("ioerr")
    assert svc.status("ioerr").status == "READY_FOR_DELIVERY"
    _seal_absent(ws)


def test_the_scan_reads_in_bounded_chunks(tmp_path):
    """The seam test alone would also pass a whole-file read; this is what pins streaming.

    Without it "scan the large file" could be satisfied by loading 2.5 MB — and later an arbitrarily
    large artifact — entirely into memory.
    """
    svc, _ = _ready_for_delivery(tmp_path, "bounded", {"big.txt": _text_over_cap().encode("utf-8")})
    real_open = builtins.open
    sizes: list[int] = []

    class _Recording:
        def __init__(self, fh):
            self._fh = fh

        def read(self, *a, **kw):
            data = self._fh.read(*a, **kw)
            sizes.append(len(data))
            return data

        def __getattr__(self, name):
            return getattr(self._fh, name)

        def __enter__(self):
            self._fh.__enter__()
            return self

        def __exit__(self, *exc):
            return self._fh.__exit__(*exc)

    def _wrapped(file, *a, **kw):
        fh = real_open(file, *a, **kw)
        return _Recording(fh) if str(file).endswith("big.txt") else fh

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(builtins, "open", _wrapped)
        manifest = svc.prepare_delivery("bounded")

    # Tie the reads to the SCAN. Without this the test passes on the unfixed tree, because the
    # existing hasher already reads in 64 KiB chunks — bounded reads by an unrelated pass would be
    # mistaken for a streaming scanner.
    assert _dispositions(manifest)["big.txt"].get("disposition") == "scanned_text"
    assert sizes, "big.txt was never opened through a normal read path"
    assert max(sizes) <= 4 * 1024 * 1024, (
        f"a single read returned {max(sizes)} bytes — the file is being slurped, not streamed"
    )
    assert len([s for s in sizes if s]) > 1, (
        "the file was read in one call; nothing bounds the memory an arbitrarily large artifact costs"
    )


# --- the two scan sites must agree ---------------------------------------------------------------

def test_delivery_documents_and_artifacts_are_both_covered_exactly_once(tmp_path):
    """Coverage must span the same set the manifest seals, with no member counted twice."""
    svc, _ = _ready_for_delivery(tmp_path, "cover", {"big.txt": _text_over_cap().encode("utf-8")})
    manifest = svc.prepare_delivery("cover")

    sealed = set(manifest["included_files"])
    covered = [e.get("path") for e in (manifest.get("content_scan") or {}).get("files") or []]
    assert sealed == set(covered), (
        f"sealed but unrecorded: {sorted(sealed - set(covered))}; "
        f"recorded but unsealed: {sorted(set(covered) - sealed)}"
    )
    assert len(covered) == len(set(covered)), "a member is recorded twice in the coverage record"
    # The generated delivery documents are part of the sealed set, so they must be covered too.
    assert "DELIVERY_REPORT.md" in sealed and "DELIVERY_REPORT.md" in covered


def test_the_scanned_hash_is_the_hash_that_gets_sealed(tmp_path):
    """Closes the scan-vs-seal gap: proving a file was scanned means nothing if other bytes ship."""
    svc, _ = _ready_for_delivery(tmp_path, "toctou", {"big.txt": _text_over_cap().encode("utf-8")})
    manifest = svc.prepare_delivery("toctou")

    entry = _dispositions(manifest)["big.txt"]
    assert entry.get("sha256"), f"the scan records no hash, so it cannot be tied to the seal: {entry}"
    assert entry["sha256"] == manifest["artifact_hashes"]["big.txt"], (
        "the bytes recorded as scanned are not the bytes recorded as sealed"
    )


def test_a_refused_delivery_leaves_the_previous_state_untouched(tmp_path):
    """Nothing half-written: no manifest, no seal, no transition, and history unadvanced."""
    svc, ws = _ready_for_delivery(
        tmp_path, "atomic", {"big.txt": _text_over_cap(secret_at=_OLD_CAP + 10).encode("utf-8")})
    before = json.loads((ws / "VALIDATED_ARTIFACTS.json").read_text(encoding="utf-8"))

    with pytest.raises(WorkExecutionError):
        svc.prepare_delivery("atomic")

    assert svc.status("atomic").status == "READY_FOR_DELIVERY"
    _seal_absent(ws)
    assert json.loads((ws / "VALIDATED_ARTIFACTS.json").read_text(encoding="utf-8")) == before
    assert not (ws / "DELIVERY_HISTORY.json").exists() or "prepared" not in (
        ws / "DELIVERY_HISTORY.json").read_text(encoding="utf-8")
