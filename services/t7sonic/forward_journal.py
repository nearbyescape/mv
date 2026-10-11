"""T7Sonic Phase 2S offline durability prototype; NOT a live market recorder.

This file deliberately lives OUTSIDE the sealed market-research Docker image.
It opens only the explicit journal path supplied by an offline test caller;
it has no exchange/network access, no scheduler, no orders, no Telegram,
no timestamp attestation and no prospective data claim.

One exclusive writer per private directory; canonical UTF-8 JSONL records
with O_APPEND, fsync, and a full fail-closed chain scan upon reopen. Local
hashes and fsync cannot prevent a privileged operator from rewriting history.
External independently timestamped receipts remain a separate prerequisite.
"""
from __future__ import annotations

from collections import Counter
import fcntl
import json
import os
from pathlib import Path
import stat

from app.research.t7sonic_forward_coverage import validate_synthetic_packet
from app.research.t7sonic_forward_protocol import FIRST_PREVIOUS_SHA

MAX_RECORD_BYTES = 32_768
JOURNAL_STATUS = "OFFLINE_SYNTHETIC_JOURNAL_NOT_INDEPENDENT_EVIDENCE"


def _canonical(packet: dict) -> bytes:
    return (json.dumps(packet, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _unique_pairs(pairs):
    record = {}
    for key, value in pairs:
        if key in record:
            raise ValueError("Duplicate JSON object key in journal")
        record[key] = value
    return record


class OfflineSyntheticJournal:
    """Exclusive, restart-recoverable, offline synthetic packet writer.

    The caller creates a PRIVATE absolute parent directory (0700).
    Existing records are never truncated, migrated or repaired by this
    component. A torn final line raises and requires forensic retention.
    """

    def __init__(self, file_path: Path) -> None:
        self.path = file_path
        self.fd: int | None = None
        self.previous_sha = FIRST_PREVIOUS_SHA
        self.previous_boundary: int | None = None
        self.records = 0
        self.counts: Counter[str] = Counter()

    def __enter__(self):
        parent = self.path.parent if isinstance(self.path, Path) else None
        if (parent is None or not self.path.is_absolute()
                or self.path.is_symlink()
                or not parent.is_dir() or parent.is_symlink()
                or (parent.stat().st_mode & 0o077) != 0):
            raise ValueError("Absolute journal in private 0700 non-symlink directory required")
        flags = os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
        was_absent = not self.path.exists()
        fd = os.open(self.path, flags, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_nlink != 1):
                raise ValueError("Invalid journal file owner, permission or hardlink")
            self.fd = fd
            if was_absent:
                os.fsync(fd)
                parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
            self._scan_all()
            return self
        except BaseException:
            self.fd = None
            os.close(fd)
            raise

    def _scan_all(self):
        assert self.fd is not None
        os.lseek(self.fd, 0, os.SEEK_SET)
        with os.fdopen(os.dup(self.fd), "rb") as reader:
            while True:
                line = reader.readline(MAX_RECORD_BYTES + 1)
                if not line:
                    break
                if len(line) > MAX_RECORD_BYTES or not line.endswith(b"\n"):
                    raise ValueError("Truncated, overlong or torn offline journal record")
                try:
                    packet = json.loads(line, object_pairs_hook=_unique_pairs)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise ValueError("Corrupt JSON record in offline journal") from exc
                if _canonical(packet) != line:
                    raise ValueError("Journal requires exact canonical JSON lines")
                digest, boundary, category = validate_synthetic_packet(
                    packet, self.previous_sha, self.previous_boundary
                )
                self.previous_sha = digest
                self.previous_boundary = boundary
                self.counts[category] += 1
                self.records += 1

    def append(self, packet: dict) -> dict:
        if self.fd is None:
            raise RuntimeError("Journal must be held with an exclusive lock")
        digest, boundary, category = validate_synthetic_packet(
            packet, self.previous_sha, self.previous_boundary
        )
        serialized = _canonical(packet)
        if len(serialized) > MAX_RECORD_BYTES:
            raise ValueError("Oversize journal event")
        written = os.write(self.fd, serialized)
        if written != len(serialized):
            raise OSError("Short append; preserve damaged journal for forensics")
        os.fsync(self.fd)
        self.previous_sha = digest
        self.previous_boundary = boundary
        self.counts[category] += 1
        self.records += 1
        return self.summary()

    def summary(self) -> dict:
        if self.fd is None:
            raise RuntimeError("Journal must be open")
        return {
            "status": JOURNAL_STATUS,
            "records": self.records,
            "watch_cycles": self.counts["WATCH_CYCLE_COMPLETE"],
            "gap_cycles": self.counts["MISSING_DATA_CYCLE"],
            "last_boundary_ms": self.previous_boundary,
            "last_sha256": self.previous_sha,
            "locally_fsynced_only": True,
            "external_time_witness": False,
            "real_exchange_source": False,
            "live_collector_enabled": False,
            "orders_authorized": False,
            "signals_authorized": False,
        }

    def __exit__(self, exc_type, exc_value, traceback):
        if self.fd is not None:
            fd = self.fd
            self.fd = None
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
        return False
