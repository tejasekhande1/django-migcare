"""
Tests for migcare.git_hooks — install / remove / detect ghost migrations.
"""

import stat
import subprocess
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def git_repo(tmp_path):
    """Create a minimal git repository in tmp_path and return its root."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    return tmp_path


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------


class TestInstall:
    def test_creates_hook_file(self, git_repo):
        from migcare.git_hooks import HOOK_NAME, install

        hook_path = install(git_repo)
        assert hook_path.exists()
        assert hook_path.name == HOOK_NAME

    def test_hook_is_executable(self, git_repo):
        from migcare.git_hooks import install

        hook_path = install(git_repo)
        assert hook_path.stat().st_mode & stat.S_IEXEC

    def test_hook_contains_marker(self, git_repo):
        from migcare.git_hooks import _BLOCK_START, install

        hook_path = install(git_repo)
        assert _BLOCK_START in hook_path.read_text()

    def test_idempotent(self, git_repo):
        from migcare.git_hooks import _BLOCK_START, install

        install(git_repo)
        hook_path = install(git_repo)  # second call
        content = hook_path.read_text()
        assert content.count(_BLOCK_START) == 1

    def test_appends_to_existing_hook(self, git_repo):
        hooks_dir = git_repo / ".git" / "hooks"
        hooks_dir.mkdir(exist_ok=True)
        existing = hooks_dir / "post-checkout"
        existing.write_text("#!/bin/bash\n# my existing hook\nexit 0\n")
        existing.chmod(existing.stat().st_mode | stat.S_IEXEC)

        from migcare.git_hooks import _BLOCK_START, install

        hook_path = install(git_repo)
        content = hook_path.read_text()
        assert "# my existing hook" in content
        assert _BLOCK_START in content

    def test_raises_when_no_git_repo(self, tmp_path):
        from migcare.git_hooks import install

        non_repo = tmp_path / "not_a_repo"
        non_repo.mkdir()
        with pytest.raises(FileNotFoundError):
            install(non_repo)


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------


class TestRemove:
    def test_removes_installed_hook(self, git_repo):
        from migcare.git_hooks import install, remove

        install(git_repo)
        changed = remove(git_repo)

        assert changed is True
        hook_path = git_repo / ".git" / "hooks" / "post-checkout"
        assert not hook_path.exists()

    def test_returns_false_when_not_installed(self, git_repo):
        from migcare.git_hooks import remove

        changed = remove(git_repo)
        assert changed is False

    def test_preserves_non_migcare_content(self, git_repo):
        hooks_dir = git_repo / ".git" / "hooks"
        hooks_dir.mkdir(exist_ok=True)
        existing = hooks_dir / "post-checkout"
        existing.write_text("#!/bin/bash\n# keep me\nexit 0\n")
        existing.chmod(existing.stat().st_mode | stat.S_IEXEC)

        from migcare.git_hooks import _BLOCK_START, install, remove

        install(git_repo)
        remove(git_repo)

        # File still exists because it contained non-migcare content
        assert existing.exists()
        assert "# keep me" in existing.read_text()
        assert _BLOCK_START not in existing.read_text()
