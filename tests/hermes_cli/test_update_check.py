"""Tests for the update check mechanism in hermes_cli.banner."""

import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest




def test_check_for_updates_uses_cache(tmp_path, monkeypatch):
    """When cache is fresh, check_for_updates should return cached value without calling git."""
    from hermes_cli.banner import check_for_updates
    from hermes_cli import __version__

    # Create a fake git repo and fresh cache
    repo_dir = tmp_path / "hermes-agent"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()

    cache_file = tmp_path / ".update_check"
    cache_file.write_text(
        json.dumps(
            {"ts": time.time(), "behind": 3, "rev": "current-head", "ver": __version__}
        )
    )

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    with patch("hermes_cli.banner._git_stdout", return_value="current-head"):
        with patch("hermes_cli.banner.subprocess.run") as mock_run:
            result = check_for_updates()

    assert result == 3
    mock_run.assert_not_called()


def test_check_for_updates_invalidates_cache_when_local_head_changes(
    tmp_path, monkeypatch
):
    """A fresh cache from the old HEAD must not survive a successful update."""
    from hermes_cli.banner import check_for_updates
    from hermes_cli import __version__

    repo_dir = tmp_path / "hermes-agent"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()

    cache_file = tmp_path / ".update_check"
    cache_file.write_text(
        json.dumps({"ts": time.time(), "behind": 2, "rev": "old-head", "ver": __version__})
    )

    def fake_git_stdout(args, cwd=None):
        if args == ["rev-parse", "HEAD"]:
            return "new-head"
        if args == ["remote", "get-url", "origin"]:
            return "https://github.com/NousResearch/hermes-agent.git"
        if args == ["rev-parse", "--is-shallow-repository"]:
            return "false"
        return None

    def fake_run(args, **kwargs):
        if args[:3] == ["git", "rev-list", "--count"]:
            return SimpleNamespace(returncode=0, stdout="0")
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    with patch("hermes_cli.banner._git_stdout", side_effect=fake_git_stdout):
        with patch("hermes_cli.banner.subprocess.run", side_effect=fake_run):
            result = check_for_updates()

    assert result == 0
    cached = json.loads(cache_file.read_text(encoding="utf-8"))
    assert cached["behind"] == 0
    assert cached["rev"] == "new-head"






def test_prefetch_non_blocking():
    """prefetch_update_check() should return immediately without blocking."""
    import hermes_cli.banner as banner

    # Reset module state
    banner._update_result = None
    banner._update_check_done = threading.Event()

    with patch.object(banner, "check_for_updates", return_value=5):
        start = time.monotonic()
        banner.prefetch_update_check()
        elapsed = time.monotonic() - start

        # Should return almost immediately (well under 1 second)
        assert elapsed < 1.0

        # Wait for the background thread to finish
        banner._update_check_done.wait(timeout=5)
        assert banner._update_result == 5



