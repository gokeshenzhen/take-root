from __future__ import annotations

from pathlib import Path

import pytest

from take_root.frontmatter import (
    FrontmatterError,
    parse_frontmatter,
    read_frontmatter_file,
    serialize_frontmatter,
)


def test_parse_and_serialize_roundtrip() -> None:
    text = "---\nartifact: sample\ncount: 3\nunknown_key:\n  nested: true\n---\n# Body\nhello\n"
    parsed = parse_frontmatter(text)
    assert parsed.metadata["artifact"] == "sample"
    assert parsed.metadata["unknown_key"]["nested"] is True
    output = serialize_frontmatter(parsed.metadata, parsed.body)
    reparsed = parse_frontmatter(output)
    assert reparsed.metadata == parsed.metadata
    assert reparsed.body == parsed.body


def test_parse_missing_delimiter_raises() -> None:
    with pytest.raises(FrontmatterError):
        parse_frontmatter("# no frontmatter\n")


def test_read_frontmatter_file(tmp_path: Path) -> None:
    file_path = tmp_path / "artifact.md"
    file_path.write_text("---\nname: demo\n---\ncontent\n", encoding="utf-8")
    parsed = read_frontmatter_file(file_path)
    assert parsed.metadata["name"] == "demo"
    assert parsed.body == "content\n"
