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


def _minimal_png() -> bytes:
    """A structurally valid 1x1 PNG — header, IHDR, IDAT and IEND with real CRCs.

    Magic bytes plus zero padding is not a PNG. Using one as the "allowed binary" fixture would let
    an admission rule that only checks eight bytes look correct.
    """
    import struct
    import zlib

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
            + _chunk(b"IEND", b""))


_MINIMAL_PNG = _minimal_png()


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


def _two_run_password_body(boundary: int = 256 * 1024) -> tuple[str, int]:
    """The reviewer's carry bypass: two long whitespace runs, decided one character into the next read.

    Returns the body and the length of the first read, so a guard can assert the two properties that
    make the case meaningful — undecidable within the first chunk, decidable once joined.
    """
    # The leading newline matters: every production pattern is `\b`-anchored, and butting `password`
    # against a filler letter produces a file with no detectable secret at all.
    tail = "\npassword" + " " * 40_000 + "=" + " " * 40_000 + "abc"
    head = _filler(boundary - len(tail))
    return head + tail + "defghijkl" + _filler(600_000), boundary


def _two_run_password_body_over_ceiling(boundary: int = 256 * 1024) -> tuple[str, int]:
    """The same two-run candidate, but reaching back further than the 1 MiB pending policy allows.

    Below the ceiling the candidate must be preserved and the secret caught. Above it the member
    must be REFUSED by name — the one thing that must never happen is cropping the window so the
    anchor disappears, which silently converts an undecided secret into a clean verdict.
    """
    tail = "\npassword" + " " * 700_000 + "=" + " " * 700_000 + "abc"
    return tail + "defghijkl" + _filler(600_000), boundary


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

    # The carry-bypass fixture is only a bypass if it is genuinely undecidable within the first read
    # and genuinely a secret once the reads are joined. Both halves are asserted, because this exact
    # fixture silently lost its word boundary once already and the test then proved nothing.
    body, first_read = _two_run_password_body()
    scanner = ContentSecretScanner()
    assert not scanner.scan_text("big.txt", body[:first_read]), (
        "the bypass fixture is already decidable inside the first read, so it does not exercise "
        "the carry at all"
    )
    assert scanner.scan_text("big.txt", body), (
        "the bypass fixture contains no secret once joined, so demanding a refusal proves nothing"
    )

    # Same two properties for the over-ceiling variant. Without them "it refused" could mean the
    # member was refused for some unrelated reason rather than because an undecided candidate
    # outran the policy.
    over, over_first = _two_run_password_body_over_ceiling()
    assert not scanner.scan_text("big.txt", over[:over_first]), (
        "the over-ceiling fixture is already decidable inside the first read"
    )
    assert scanner.scan_text("big.txt", over), (
        "the over-ceiling fixture contains no real secret, so refusing it proves nothing"
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
    # The byte count must come from the stream that was actually read. A member can grow between a
    # pre-read stat() and the read itself, and a manifest that reports the stale number attests to
    # something nobody saw.
    assert disp["big.txt"]["bytes"] == len(_text_over_cap().encode("utf-8"))


def test_the_recorded_size_comes_from_the_stream_not_from_a_pre_read_stat(tmp_path):
    """A member can grow between `stat()` and the read; the manifest must attest to what was read.

    With the size taken from `stat()`, an under-reporting stat also slips past the ceiling check,
    which is why this pins the streamed count rather than merely asserting a number.
    """
    content = _text_over_cap().encode("utf-8")
    svc, _ = _ready_for_delivery(tmp_path, "stat", {"big.txt": content})
    real_stat = Path.stat

    class _UnderReporting:
        st_size = 10

        def __init__(self, st):
            self._st = st

        def __getattr__(self, name):
            return getattr(self._st, name)

    def _lying_stat(self, *a, **kw):
        st = real_stat(self, *a, **kw)
        return _UnderReporting(st) if self.name == "big.txt" else st

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "stat", _lying_stat)
        manifest = svc.prepare_delivery("stat")

    assert _dispositions(manifest)["big.txt"]["bytes"] == len(content), (
        "the manifest reports the size a stat() claimed rather than the bytes actually streamed"
    )


def test_a_member_changed_between_the_validation_check_and_the_scan_is_refused(tmp_path):
    """Closes the second TOCTOU window: validated, then swapped, then scanned and sealed.

    The validated-snapshot comparison reads the files once; the scan reads them again. A member
    replaced in between would be scanned and sealed while never having been validated.
    """
    svc, ws = _ready_for_delivery(tmp_path, "drift", {"big.txt": _text_over_cap().encode("utf-8")})
    original = WorkExecutionService._hash_map

    def _mutating(self, pid, rels):
        result = original(self, pid, rels)
        # Deliberately CLEAN replacement bytes. Swapping in a secret would be caught by the scan
        # itself, and the test would pass without the validated-snapshot comparison existing at all.
        # Different, clean, and never validated is the case that must refuse.
        (ws / "big.txt").write_bytes((_text_over_cap() + "appended after validation\n")
                                     .encode("utf-8"))
        return result

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(WorkExecutionService, "_hash_map", _mutating)
        with pytest.raises(WorkExecutionError) as exc:
            svc.prepare_delivery("drift")
    assert "big.txt" in str(exc.value), f"the refusal does not name the member: {exc.value}"
    assert svc.status("drift").status == "READY_FOR_DELIVERY"
    _seal_absent(ws)


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


def test_a_secret_split_by_two_long_whitespace_runs_still_blocks(tmp_path):
    """The bypass a fixed carry cannot cover, and the reason the carry is now candidate-driven.

    `password_assignment` is `\\bpass(?:word|wd)?\\s*[:=]\\s*['"]?[^\\s'"]{4,}` — two independently
    unbounded whitespace runs before the four value characters. `password`, 40 KiB of spaces, `=`,
    40 KiB more, then three value characters at the end of one read and the fourth in the next: the
    first pass cannot match, and any fixed-length carry has already dropped the keyword. A carry
    measured in characters loses this secret silently; one that keeps the pending candidate does not.
    """
    body, _ = _two_run_password_body()
    svc, ws = _ready_for_delivery(tmp_path, "wsplit", {"big.txt": body.encode("utf-8")})

    with pytest.raises(WorkExecutionError) as exc:
        svc.prepare_delivery("wsplit")
    assert "big.txt" in str(exc.value), f"the refusal does not name the file: {exc.value}"
    _seal_absent(ws)


def test_a_two_run_candidate_past_the_pending_ceiling_fails_closed(tmp_path):
    """Above the policy the member is refused; the anchor is never cropped away first.

    The previous implementation sliced the buffer to the last 1 MiB *before* looking for a pending
    candidate, so a candidate reaching back further than the ceiling vanished from the window: no
    refusal fired, the prefix was discarded, and the completed secret was never seen. Preserving a
    candidate below the ceiling (the 40 KiB test above) does not prove enforcement above it.
    """
    body, _ = _two_run_password_body_over_ceiling()
    svc, ws = _ready_for_delivery(tmp_path, "ceil", {"big.txt": body.encode("utf-8")})

    with pytest.raises(WorkExecutionError) as exc:
        svc.prepare_delivery("ceil")
    assert "big.txt" in str(exc.value), f"the refusal does not name the member: {exc.value}"
    assert svc.status("ceil").status == "READY_FOR_DELIVERY"
    _seal_absent(ws)


def test_png_magic_in_a_text_artifact_fails_closed(tmp_path):
    """A signature alone may not admit a file: prepending eight bytes would bypass the whole scan."""
    blob = b"\x89PNG\r\n\x1a\n" + b"\xff\xfe" + SECRET.encode("utf-8") + bytes(64)
    svc, ws = _ready_for_delivery(tmp_path, "pngtxt", {"notes.txt": blob})

    with pytest.raises(WorkExecutionError) as exc:
        svc.prepare_delivery("pngtxt")
    assert "notes.txt" in str(exc.value)
    _seal_absent(ws)


def test_a_mismatched_signature_under_an_expected_extension_fails_closed(tmp_path):
    """`.png` is an expected evidence type, but these are not the bytes of one."""
    blob = b"PK\x03\x04" + b"\xff\xfe" + SECRET.encode("utf-8") + bytes(64)
    svc, ws = _ready_for_delivery(tmp_path, "zippng", {"evidence/shot.png": blob})

    with pytest.raises(WorkExecutionError) as exc:
        svc.prepare_delivery("zippng")
    assert "shot.png" in str(exc.value)
    _seal_absent(ws)


def test_a_verified_binary_evidence_is_named_in_the_successful_manifest(tmp_path):
    """A real PNG is an allowed limitation — but only when recorded explicitly, per path."""
    svc, _ = _ready_for_delivery(tmp_path, "png", {"evidence/shot.png": _MINIMAL_PNG})

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

    class _FailsLargeReads:
        """Lets the existing 64 KiB hasher through and fails only the scan's larger read.

        Without that split the test passes on the old hasher's raw OSError and proves nothing about
        the scan path.
        """

        def __init__(self, fh):
            self._fh = fh

        def read(self, *a, **kw):
            if a and a[0] and a[0] > 65536:
                raise OSError("injected read failure")
            return self._fh.read(*a, **kw)

        def __getattr__(self, name):
            return getattr(self._fh, name)

        def __enter__(self):
            self._fh.__enter__()
            return self

        def __exit__(self, *exc):
            return self._fh.__exit__(*exc)

    def _boom(file, *a, **kw):
        fh = real_open(file, *a, **kw)
        return _FailsLargeReads(fh) if str(file).endswith("big.txt") else fh

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(builtins, "open", _boom)
        with pytest.raises(WorkExecutionError) as exc:
            svc.prepare_delivery("ioerr")
    assert "big.txt" in str(exc.value), (
        f"an unreadable member must be refused by path, not by a bare OSError: {exc.value}"
    )
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
    # Well under the ~2.55 MiB fixture, so a whole-file read cannot satisfy it. The bound applies to
    # every reader of this path, which is what makes it a memory guarantee rather than a claim about
    # one function.
    assert max(sizes) <= 512 * 1024, (
        f"a single read returned {max(sizes)} bytes — the file is being slurped, not streamed"
    )
    assert sum(sizes) >= len(_text_over_cap().encode("utf-8")), (
        "fewer bytes were read than the file holds, so it was not scanned end to end"
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
