"""Campaign run-lock (v3.3) — prevents overlapping runs of the SAME campaign (e.g. a scheduled run
firing while a manual run is still going). Atomic O_EXCL lock file with a lease so a crashed run does
not wedge the campaign forever. Fresh-process safe. No secrets.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable, Optional


class CampaignBusy(RuntimeError):
    """Raised when the same campaign is already running (no overlap allowed)."""


class CampaignRunLock:
    def __init__(self, output_dir: str, campaign_id: str, *, lease_s: float = 1800.0,
                 clock: Callable[[], float] = time.time) -> None:
        safe = "".join(c for c in campaign_id if c.isalnum() or c in "-_")[:80] or "campaign"
        self._path = Path(output_dir) / "scout" / "_registry" / f"run-{safe}.lock"
        self._lease_s = lease_s
        self._clock = clock
        self._held = False

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        now = self._clock()
        try:
            fd = os.open(str(self._path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, json.dumps({"pid": os.getpid(), "until": now + self._lease_s}).encode())
            os.close(fd)
            self._held = True
            return
        except FileExistsError:
            # The lock EXISTS - that is what FileExistsError proves. Anything we cannot read about
            # it leaves the lease state UNKNOWN, and an unknown lease is HELD, not free: reclaiming
            # it starts a second concurrent run against the same targets, which is the one thing
            # this lock exists to prevent. The writer is `os.open` + `os.write` with no fsync, so a
            # crash mid-write leaves exactly the partial JSON that used to be read as "expired".
            #
            # `float()` is inside the guarded block too: it used to sit outside, so `until: null`
            # raised TypeError and `until: "soon"` raised ValueError straight out of `acquire`
            # instead of failing closed.
            try:
                info = json.loads(self._path.read_text(encoding="utf-8"))
                until = float(info["until"])
            except (OSError, ValueError, TypeError, KeyError):
                raise CampaignBusy(
                    "a campaign lock exists but its lease could not be read; refusing to reclaim "
                    "it - an unreadable lock is held, not expired") from None
            if until > now:
                raise CampaignBusy(
                    f"campaign is already running (lock held until {info.get('until')}); "
                    "no overlapping run is started") from None
            # genuinely expired lease -> reclaim
            self._path.write_text(json.dumps({"pid": os.getpid(), "until": now + self._lease_s}),
                                  encoding="utf-8")
            self._held = True

    def release(self) -> None:
        if self._held:
            try:
                self._path.unlink()
            except OSError:
                pass
            self._held = False

    def __enter__(self) -> "CampaignRunLock":
        self.acquire()
        return self

    def __exit__(self, *_exc) -> None:
        self.release()


def read_lock(output_dir: str, campaign_id: str) -> Optional[dict]:
    safe = "".join(c for c in campaign_id if c.isalnum() or c in "-_")[:80] or "campaign"
    p = Path(output_dir) / "scout" / "_registry" / f"run-{safe}.lock"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
