from __future__ import annotations

from take_root.phases.code import _resolved_vcs_metadata


def test_resolved_vcs_metadata_falls_back_to_ruby_artifact_values() -> None:
    ruby_meta = {
        "commit_sha": "138e300d9b6e8daadd93830a0229c9b061caded3",
        "snapshot_dir": ".take_root/code/snapshots/r1",
    }

    result = _resolved_vcs_metadata(
        ruby_meta,
        {"commit_sha": None, "snapshot_dir": None},
    )

    assert result["commit_sha"] == "138e300d9b6e8daadd93830a0229c9b061caded3"
    assert result["snapshot_dir"] == ".take_root/code/snapshots/r1"


def test_resolved_vcs_metadata_prefers_new_vcs_result() -> None:
    ruby_meta = {
        "commit_sha": "old-sha",
        "snapshot_dir": ".take_root/code/snapshots/r1",
    }

    result = _resolved_vcs_metadata(
        ruby_meta,
        {"commit_sha": "new-sha", "snapshot_dir": ".take_root/code/snapshots/r2"},
    )

    assert result["commit_sha"] == "new-sha"
    assert result["snapshot_dir"] == ".take_root/code/snapshots/r2"
