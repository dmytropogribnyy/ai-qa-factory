"""Reading a recording well enough to say whether it is one.

A ``.webm`` on disk with a plausible byte count proves nothing. A file can be non-empty, correctly
named, referenced from a manifest and still be a single black frame, a truncated write, or a
container no player will open. "A video was captured" is exactly the kind of claim that is easy to
make and expensive to be wrong about, so it is derived here from the file's own structure.

This parses just enough Matroska/EBML to answer four questions:

- does the container parse at all;
- what are the pixel dimensions;
- what is the duration, and is it finite and above zero;
- do the encoded blocks span time, or is everything stamped at the same instant?

The last one is the one that matters. Duration is a number written into a header — a file claiming
eight seconds and containing one frame would pass every other check. Cluster timecodes are produced
by the encoder as it writes, so a spread across them is evidence that something actually moved.

``ffprobe`` would answer these too, and is used as a cross-check when present. It is not required:
a verification that only works on machines with ffmpeg installed is not a verification the product
can rely on.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

# The handful of EBML ids this needs. Everything else is skipped by size.
_SEGMENT = 0x18538067
_INFO = 0x1549A966
_TRACKS = 0x1654AE6B
_TRACK_ENTRY = 0xAE
_VIDEO = 0xE0
_CLUSTER = 0x1F43B675
_MASTERS = {_SEGMENT, _INFO, _TRACKS, _TRACK_ENTRY, _VIDEO, _CLUSTER}

_TIMECODE_SCALE = 0x2AD7B1
_DURATION = 0x4489
_PIXEL_WIDTH = 0xB0
_PIXEL_HEIGHT = 0xBA
_CLUSTER_TIMECODE = 0xE7
_SIMPLE_BLOCK = 0xA3
_BLOCK = 0xA1

_MAX_BYTES = 256 * 1024 * 1024      # a Scout clip is seconds long; anything larger is not ours
_UNKNOWN_SIZE = object()


class MediaProbeError(Exception):
    pass


def sha256_of(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_video(path) -> Dict[str, Any]:
    """Describe a recording, or say honestly why it cannot be described.

    Never raises: an unreadable clip is a fact about the clip, and the caller's job is to report it
    rather than to crash a completed run.
    """
    target = Path(path)
    out: Dict[str, Any] = {
        "ref": target.name, "container": "", "mime": "", "bytes": 0, "duration_s": None,
        "width": None, "height": None, "block_count": 0, "timespan_ms": None,
        "has_time_sequence": False, "playable": False, "sha256": "", "error": "",
        "ffprobe": None,
    }
    try:
        size = target.stat().st_size
    except OSError as exc:
        out["error"] = f"the file could not be read ({type(exc).__name__})"
        return out
    out["bytes"] = size
    if size <= 0:
        out["error"] = "the file is empty"
        return out
    if size > _MAX_BYTES:
        out["error"] = "the file is larger than any Scout recording should be"
        return out
    out["sha256"] = sha256_of(target)
    suffix = target.suffix.lower()
    out["container"] = {".webm": "webm", ".mp4": "mp4"}.get(suffix, suffix.lstrip("."))
    out["mime"] = {"webm": "video/webm", "mp4": "video/mp4"}.get(out["container"], "")
    if out["container"] != "webm":
        out["error"] = "only webm recordings are parsed without external tools"
        out["ffprobe"] = _ffprobe(target)
        return out
    try:
        parsed = _parse_webm(target.read_bytes())
    except Exception as exc:  # noqa: BLE001 - a malformed clip is a result, not a crash
        out["error"] = f"the container could not be parsed ({type(exc).__name__})"
        return out
    out.update({k: parsed[k] for k in ("duration_s", "width", "height", "block_count",
                                       "timespan_ms")})
    # "Plays" means: a real picture size, a duration above zero, and blocks that span time.
    out["has_time_sequence"] = bool(parsed["block_count"] >= 2
                                    and (parsed["timespan_ms"] or 0) > 0)
    out["playable"] = bool(out["width"] and out["height"]
                           and (out["duration_s"] or 0) > 0
                           and out["has_time_sequence"])
    if not out["playable"] and not out["error"]:
        out["error"] = _why_not_playable(out)
    out["ffprobe"] = _ffprobe(target)
    return out


def _why_not_playable(probe: Dict[str, Any]) -> str:
    if not probe["width"] or not probe["height"]:
        return "the recording declares no picture size"
    if not (probe["duration_s"] or 0) > 0:
        return "the recording has no positive duration"
    return "the recording contains no sequence of frames over time (a single static frame)"


def _ffprobe(target: Path) -> Optional[Dict[str, Any]]:
    """An independent second opinion when the host happens to have ffprobe. Never required."""
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, "-v", "error", "-show_entries", "format=duration:stream=width,height,codec_name",
             "-of", "json", str(target)],
            capture_output=True, text=True, timeout=30, check=False)
        if proc.returncode != 0:
            return {"available": True, "ok": False, "error": (proc.stderr or "")[:200]}
        data = json.loads(proc.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]
        return {"available": True, "ok": True,
                "duration_s": float((data.get("format") or {}).get("duration") or 0.0),
                "width": stream.get("width"), "height": stream.get("height"),
                "codec": stream.get("codec_name")}
    except Exception as exc:  # noqa: BLE001 - an optional cross-check never fails the probe
        return {"available": True, "ok": False, "error": f"{type(exc).__name__}"}


# --- the small EBML reader -----------------------------------------------------------------------

def _read_vint(buf: bytes, pos: int, *, keep_marker: bool):
    """Read one EBML variable-length integer. Returns ``(value, next_pos)``."""
    if pos >= len(buf):
        raise MediaProbeError("truncated element")
    first = buf[pos]
    if first == 0:
        raise MediaProbeError("invalid element width")
    length = 8 - first.bit_length() + 1
    if pos + length > len(buf):
        raise MediaProbeError("truncated element")
    value = first if keep_marker else first & (0xFF >> length)
    unknown = (first & (0xFF >> length)) == (0xFF >> length)
    for offset in range(1, length):
        byte = buf[pos + offset]
        value = (value << 8) | byte
        unknown = unknown and byte == 0xFF
    if not keep_marker and unknown:
        return _UNKNOWN_SIZE, pos + length
    return value, pos + length


def _parse_webm(buf: bytes) -> Dict[str, Any]:
    state = {"timecode_scale": 1_000_000, "duration_ticks": None, "width": None, "height": None,
             "block_count": 0, "block_times": [], "cluster_time": 0}
    _walk(buf, 0, len(buf), state, depth=0)
    scale_ms = state["timecode_scale"] / 1_000_000.0
    duration_s = None
    if state["duration_ticks"]:
        duration_s = round(state["duration_ticks"] * state["timecode_scale"] / 1e9, 3)
    # Per-BLOCK times, not per-cluster: a short recording is written as a single cluster, so the
    # spread between clusters is zero and says nothing. The blocks inside carry the real timeline.
    times: List[int] = sorted(state["block_times"])
    timespan_ms = None
    if times:
        timespan_ms = int((times[-1] - times[0]) * scale_ms)
        # A finalized Playwright clip normally carries Duration; when it does not, the last frame
        # is the honest lower bound rather than "unknown".
        if duration_s is None and timespan_ms > 0:
            duration_s = round(timespan_ms / 1000.0, 3)
    return {"duration_s": duration_s, "width": state["width"], "height": state["height"],
            "block_count": state["block_count"], "timespan_ms": timespan_ms}


def _block_time(payload: bytes, cluster_time: int) -> Optional[int]:
    """Absolute timecode of one block: ``[track vint][int16 relative][flags][frame]``."""
    try:
        _track, pos = _read_vint(payload, 0, keep_marker=False)
        if pos + 2 > len(payload):
            return None
        return cluster_time + int.from_bytes(payload[pos:pos + 2], "big", signed=True)
    except (MediaProbeError, IndexError):
        return None


def _walk(buf: bytes, start: int, end: int, state: Dict[str, Any], *, depth: int) -> None:
    if depth > 8:
        return
    pos = start
    while pos < end:
        try:
            element_id, pos = _read_vint(buf, pos, keep_marker=True)
            size, pos = _read_vint(buf, pos, keep_marker=False)
        except MediaProbeError:
            return
        if size is _UNKNOWN_SIZE:
            # A live-written master (Segment/Cluster) whose size was never back-filled: descend and
            # let the child elements bound themselves.
            if element_id in _MASTERS:
                _walk(buf, pos, end, state, depth=depth + 1)
            return
        stop = min(end, pos + int(size))
        if element_id in _MASTERS:
            _walk(buf, pos, stop, state, depth=depth + 1)
        else:
            payload = buf[pos:stop]
            if element_id == _TIMECODE_SCALE and payload:
                state["timecode_scale"] = int.from_bytes(payload, "big")
            elif element_id == _DURATION and len(payload) in (4, 8):
                import struct
                state["duration_ticks"] = struct.unpack(
                    ">f" if len(payload) == 4 else ">d", payload)[0]
            elif element_id == _PIXEL_WIDTH and payload:
                state["width"] = int.from_bytes(payload, "big")
            elif element_id == _PIXEL_HEIGHT and payload:
                state["height"] = int.from_bytes(payload, "big")
            elif element_id == _CLUSTER_TIMECODE and payload:
                state["cluster_time"] = int.from_bytes(payload, "big")
            elif element_id in (_SIMPLE_BLOCK, _BLOCK):
                state["block_count"] += 1
                when = _block_time(payload, state["cluster_time"])
                if when is not None and len(state["block_times"]) < 20_000:
                    state["block_times"].append(when)
        pos = stop
