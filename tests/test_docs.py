"""Keep the API reference in step with the library source."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_revert_reason_is_documented():
    source = "\n".join(path.read_text() for path in (ROOT / "src" / "hyper_vyper").glob("*.vy"))
    reasons = set(re.findall(r'\)?,\s*"([A-Z][^"]+)"\s*(?:#.*)?$', source, re.MULTILINE))
    api = (ROOT / "docs" / "reference" / "api.md").read_text()
    assert reasons, "no revert reasons found"
    missing = sorted(reason for reason in reasons if f"| `{reason}` |" not in api)
    assert not missing


def test_quoted_source_still_matches():
    # A page quotes a whole file, or a line range with a marker that holds the text
    # of the range's first line. If the source moves, the marker no longer matches.
    whole = re.compile(r'--8<-- "([^":]+)"')
    ranged = re.compile(
        r'<!-- starts: "((?:[^"\\]|\\.)*)" -->\s*```(?:vyper|python)\s*--8<-- "([^":]+):(\d+):(\d+)"'
    )
    checked = 0
    for page in sorted((ROOT / "docs").rglob("*.md")):
        text = page.read_text()
        files, ranges = whole.findall(text), ranged.findall(text)
        assert text.count("--8<--") == len(files) + len(ranges), f"{page.name}: unmarked quote"
        for path in files:
            assert (ROOT / path).exists(), (page.name, path)
        for expected, path, start, end in ranges:
            lines = (ROOT / path).read_text().splitlines()
            first = lines[int(start) - 1]
            assert first.startswith(expected.replace('\\"', '"')), (page.name, path, start, first)
            assert lines[int(end) - 1].strip(), (page.name, path, end, "range ends on a blank line")
            checked += 1
    assert checked
