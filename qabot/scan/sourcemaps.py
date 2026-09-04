"""A minified stack frame, resolved back to something a person can open.

Measured across seven real applications, the highest-severity signal this tool
produces was also its least actionable: an uncaught exception arrived carrying the
message `"Wl"` -- a mangled symbol -- while a lower-severity console error carried a
real file and line. A finding a builder cannot act on is barely better than no finding,
so where an application ships its `.map` files we read them.

Hand-rolled rather than taking a dependency: we need one direction of one format --
generated position to original position -- and the whole of it is Base64 VLQ over
comma- and semicolon-separated segments.

The rule that matters is the failure mode. A map that is missing, unfetchable or
malformed produces `resolved=False` carrying the minified location unchanged, and the
report says so. Presenting an unresolved frame as though it were original would send
somebody to read a file that does not exist.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from pydantic import BaseModel

Fetch = Callable[[str], "str | None"]

_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_VLQ_SHIFT = 5
_VLQ_CONTINUE = 1 << _VLQ_SHIFT
_VLQ_MASK = _VLQ_CONTINUE - 1


class Frame(BaseModel):
    """Where an error happened. `resolved` says whether to believe the file name."""

    file: str | None = None
    line: int | None = None
    name: str | None = None
    resolved: bool = False


def decode_vlq(segment: str) -> list[int]:
    """Base64 VLQ segment to signed integers.

    Each value is a run of 6-bit groups, little-endian, the top bit marking
    continuation; the lowest bit of the assembled value carries the sign.
    """
    values, shift, accumulated = [], 0, 0
    for char in segment:
        digit = _B64.index(char)
        accumulated += (digit & _VLQ_MASK) << shift
        if digit & _VLQ_CONTINUE:
            shift += _VLQ_SHIFT
            continue
        negative = accumulated & 1
        value = accumulated >> 1
        values.append(-value if negative else value)
        shift, accumulated = 0, 0
    return values


def _lookup(raw: str, line: int, column: int) -> tuple[int, int, int] | None:
    """(source index, original line, name index) for a generated position, 0-based."""
    document = json.loads(raw)
    mappings = document.get("mappings", "")
    source_i = orig_line = orig_col = name_i = 0
    best: tuple[int, int, int] | None = None
    for generated_line, group in enumerate(mappings.split(";")):
        generated_col = 0
        for segment in group.split(","):
            if not segment:
                continue
            fields = decode_vlq(segment)
            generated_col += fields[0]
            if len(fields) >= 4:
                source_i += fields[1]
                orig_line += fields[2]
                orig_col += fields[3]
            if len(fields) >= 5:
                name_i += fields[4]
            # The mapping in force at a position is the last one at or before it.
            if generated_line == line and generated_col <= column:
                best = (source_i, orig_line, name_i if len(fields) >= 5 else -1)
        if generated_line > line:
            break
    return best


def resolve(url: str | None, line: int | None, column: int | None, fetch: Fetch) -> Frame:
    """Resolve one frame, or return it unresolved with the minified location intact."""
    if url is None or line is None:
        return Frame(file=url, line=line, resolved=False)

    unresolved = Frame(file=url, line=line, resolved=False)
    raw = fetch(url + ".map")
    if raw is None:
        return unresolved
    try:
        document = json.loads(raw)
        found = _lookup(raw, line - 1, column or 0)
    except (ValueError, KeyError, IndexError):
        return unresolved
    if found is None:
        return unresolved

    source_i, orig_line, name_i = found
    sources = document.get("sources") or []
    names = document.get("names") or []
    if not 0 <= source_i < len(sources):
        return unresolved
    return Frame(
        file=sources[source_i],
        line=orig_line + 1,
        name=names[name_i] if 0 <= name_i < len(names) else None,
        resolved=True,
    )
