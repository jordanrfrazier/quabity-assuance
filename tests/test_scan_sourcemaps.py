"""Minified frames back to original names, or an honest admission."""

from __future__ import annotations

import json

from qabot.scan.sourcemaps import decode_vlq, resolve


def test_decode_vlq_handles_sign_and_continuation() -> None:
    """Base64 VLQ: 'A' is 0, 'C' is 1, 'D' is -1, 'gB' is 16."""
    assert decode_vlq("A") == [0]
    assert decode_vlq("C") == [1]
    assert decode_vlq("D") == [-1]
    assert decode_vlq("gB") == [16]
    assert decode_vlq("AACA") == [0, 0, 1, 0]


def _map_for(sources: list[str], names: list[str], mappings: str) -> str:
    return json.dumps({"version": 3, "sources": sources, "names": names, "mappings": mappings})


def test_a_frame_resolves_to_its_original_file_line_and_name() -> None:
    """One segment on generated line 1: source 0, original line 10, name 0."""
    sourcemap = _map_for(["src/cart.ts"], ["computeTotal"], "AAUAA")
    fetch = {"https://app.test/b.js.map": sourcemap}.get

    frame = resolve("https://app.test/b.js", line=1, column=0, fetch=fetch)

    assert frame.resolved is True
    assert frame.file == "src/cart.ts"
    assert frame.line == 11  # 0-based in the map, 1-based for a human
    assert frame.name == "computeTotal"


def test_a_missing_map_degrades_to_an_unresolved_frame() -> None:
    """Never present a minified frame as if it were original."""
    frame = resolve("https://app.test/b.js", line=1, column=0, fetch=lambda _: None)
    assert frame.resolved is False
    assert frame.file == "https://app.test/b.js"
    assert frame.line == 1
    assert frame.name is None


def test_a_malformed_map_degrades_rather_than_raising() -> None:
    frame = resolve("https://app.test/b.js", 1, 0, lambda _: "not json")
    assert frame.resolved is False


def test_no_location_at_all_is_an_unresolved_frame_not_a_crash() -> None:
    frame = resolve(None, None, None, lambda _: None)
    assert frame.resolved is False
    assert frame.file is None


def test_malformed_mappings_type_degrades() -> None:
    """A non-string mappings field returns unresolved, never raises."""
    map_data = {"version": 3, "sources": ["src/cart.ts"], "names": [], "mappings": 42}
    sourcemap = json.dumps(map_data)
    fetch = {"https://app.test/b.js.map": sourcemap}.get
    frame = resolve("https://app.test/b.js", line=1, column=0, fetch=fetch)
    assert frame.resolved is False
    assert frame.file == "https://app.test/b.js"


def test_sources_as_string_does_not_fabricate_filename() -> None:
    """String sources are rejected; returned file is original URL, not a char."""
    map_data = {"version": 3, "sources": "abc", "names": [], "mappings": "AAUAA"}
    sourcemap = json.dumps(map_data)
    fetch = {"https://app.test/b.js.map": sourcemap}.get
    frame = resolve("https://app.test/b.js", line=1, column=0, fetch=fetch)
    assert frame.resolved is False
    assert frame.file == "https://app.test/b.js"
    assert frame.file != "a"  # Explicitly check we didn't fabricate


def test_names_as_string_does_not_fabricate_name() -> None:
    """String names are rejected; name field stays None."""
    map_data = {"version": 3, "sources": ["src/cart.ts"], "names": "xyz", "mappings": "AAUAA"}
    sourcemap = json.dumps(map_data)
    fetch = {"https://app.test/b.js.map": sourcemap}.get
    frame = resolve("https://app.test/b.js", line=1, column=0, fetch=fetch)
    assert frame.resolved is False
    assert frame.name is None
