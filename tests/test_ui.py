from __future__ import annotations

import io

from take_root.ui import select_option


def test_select_option_accepts_arrow_navigation() -> None:
    keys = iter(["down", "enter"])
    output = io.StringIO()
    selected = select_option(
        "选择 provider",
        ["claude_official", "codex_official"],
        "claude_official",
        output=output,
        key_reader=lambda stream: next(keys),
        interactive=True,
    )
    rendered = output.getvalue()
    assert selected == "codex_official"
    assert "●" in rendered
