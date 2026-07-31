"""Pure-Python stand-in for the compiled `uuid_utils` extension.

WHY THIS EXISTS
---------------
LangGraph depends on `uuid_utils`, which ships as a compiled Rust extension
(`_uuid_utils.pyd`). On locked-down Windows machines, Application Control
policy blocks loading that DLL, producing:

    ImportError: DLL load failed while importing _uuid_utils

`uuid_utils` is only used to generate identifiers. Nothing about it needs to be
native, so this module reimplements the same public API on top of the Python
standard library. Drop it next to your `app/` folder (the project root) and
Python will import it INSTEAD of the blocked package, because the working
directory comes before site-packages on `sys.path`.

Fully offline. No third-party imports.
"""
from __future__ import annotations

import os
import time
import uuid as _uuid
from uuid import (  # re-exported so `from uuid_utils import UUID` works
    UUID,
    NAMESPACE_DNS,
    NAMESPACE_OID,
    NAMESPACE_URL,
    NAMESPACE_X500,
    getnode,
)

__all__ = [
    "UUID", "uuid1", "uuid3", "uuid4", "uuid5", "uuid6", "uuid7", "uuid8",
    "getnode", "NAMESPACE_DNS", "NAMESPACE_URL", "NAMESPACE_OID", "NAMESPACE_X500",
]

__version__ = "0.0.0+pure-python-shim"

# ---- versions the stdlib already implements -------------------------------
uuid1 = _uuid.uuid1
uuid3 = _uuid.uuid3
uuid4 = _uuid.uuid4
uuid5 = _uuid.uuid5

# Offset between the Gregorian epoch (1582-10-15) and the Unix epoch,
# expressed in 100-nanosecond intervals.
_GREGORIAN_OFFSET = 0x01B21DD213814000

# Guarantees v6 ids keep increasing even when called inside the same tick.
_last_v6_timestamp = 0


def uuid6(node: int | None = None, clock_seq: int | None = None,
          timestamp: int | None = None) -> UUID:
    """UUID version 6 — a time-ordered reordering of v1.

    LangGraph uses this for monotonically sortable checkpoint ids.
    """
    global _last_v6_timestamp

    if timestamp is None:
        timestamp = time.time_ns() // 100 + _GREGORIAN_OFFSET
    if timestamp <= _last_v6_timestamp:
        timestamp = _last_v6_timestamp + 1
    _last_v6_timestamp = timestamp

    ts = timestamp & 0x0FFFFFFFFFFFFFFF          # 60-bit timestamp
    time_high = (ts >> 28) & 0xFFFFFFFF          # bits 127..96
    time_mid = (ts >> 12) & 0xFFFF               # bits  95..80
    time_low_and_version = (0x6 << 12) | (ts & 0x0FFF)   # bits 79..64

    if clock_seq is None:
        clock_seq = int.from_bytes(os.urandom(2), "big")
    clock = 0x8000 | (clock_seq & 0x3FFF)        # variant 0b10 + 14-bit seq

    if node is None:
        # Random node with the multicast bit set, per RFC recommendation.
        node = int.from_bytes(os.urandom(6), "big") | (1 << 40)

    value = (
        (time_high << 96)
        | (time_mid << 80)
        | (time_low_and_version << 64)
        | (clock << 48)
        | (node & 0xFFFFFFFFFFFF)
    )
    return UUID(int=value)


def uuid7(timestamp: int | None = None) -> UUID:
    """UUID version 7 — 48-bit Unix millisecond prefix, then randomness."""
    ms = int(time.time() * 1000) if timestamp is None else int(timestamp)
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF          # 12 bits
    rand_b = int.from_bytes(os.urandom(8), "big") & 0x3FFFFFFFFFFFFFFF  # 62 bits
    value = (
        ((ms & 0xFFFFFFFFFFFF) << 80)
        | (0x7 << 76)      # version
        | (rand_a << 64)
        | (0x2 << 62)      # variant 0b10
        | rand_b
    )
    return UUID(int=value)


def uuid8(bytes_: bytes) -> UUID:
    """UUID version 8 — caller-supplied bytes with version/variant applied."""
    raw = bytearray(bytes_[:16].ljust(16, b"\x00"))
    raw[6] = (raw[6] & 0x0F) | 0x80   # version 8
    raw[8] = (raw[8] & 0x3F) | 0x80   # variant 0b10
    return UUID(bytes=bytes(raw))
