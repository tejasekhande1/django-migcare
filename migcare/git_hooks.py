"""
Git hook management for django-migcare.

Installs / removes a ``post-checkout`` hook that warns when a branch switch
leaves the database with "ghost" migrations — i.e. migrations that are recorded
as applied in the DB but whose files no longer exist on the new branch.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from typing import Optional

HOOK_NAME = "post-checkout"

# Start/end markers let us surgically insert and remove the migcare block
# even when the file contains an existing user-written hook.
_BLOCK_START = "# >>>>> django-migcare post-checkout hook (start) <<<<<"
_BLOCK_END = "# >>>>> django-migcare post-checkout hook (end) <<<<<"

_MIGCARE_MARKER = _BLOCK_START  # used for "is installed?" checks

# When the hook file doesn't exist yet, we create it with a shebang so it is
# directly executable.  When we append to an existing hook the shebang is
# already present, so we omit it.
_HOOK_SHEBANG = "#!/usr/bin/env bash\n"

_HOOK_BLOCK = """\
{start}
# Warns when the DB has applied migrations absent from the current branch.
# To remove: python manage.py migcare_install_hooks --remove

PREV_HEAD="$1"
NEW_HEAD="$2"
BRANCH_SWITCH="$3"

if [ "$BRANCH_SWITCH" = "1" ] && [ "$PREV_HEAD" != "$NEW_HEAD" ]; then
    REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
    MANAGE_PY=$(find "$REPO_ROOT" -maxdepth 3 -name "manage.py" 2>/dev/null | head -1)
    if [ -n "$MANAGE_PY" ]; then
        python "$MANAGE_PY" migcare_check --git-post-checkout "$PREV_HEAD" "$NEW_HEAD" 2>/dev/null || true
    fi
fi
{end}
""".format(start=_BLOCK_START, end=_BLOCK_END)


def _find_git_dir(start: Path) -> Optional[Path]:
    """Walk up from *start* looking for a .git directory."""
    current = start.resolve()
    for parent in [current, *current.parents]:
        git_dir = parent / ".git"
        if git_dir.is_dir():
            return git_dir
        if git_dir.is_file():
            # git worktree — .git is a file pointing to the real git dir
            content = git_dir.read_text().strip()
            if content.startswith("gitdir:"):
                return Path(content.split(":", 1)[1].strip())
    return None


def install(project_root: Path) -> Path:
    """
    Install the post-checkout hook into the repository found at or above
    *project_root*.

    If the hook file already exists and was NOT installed by migcare, the
    migcare script is appended after a blank line so the original hook is
    preserved.

    Returns the path of the hook file written.
    Raises ``FileNotFoundError`` if no git repository is found.
    """
    git_dir = _find_git_dir(project_root)
    if git_dir is None:
        raise FileNotFoundError(
            "No git repository found. Run this command from within a git repo."
        )

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    hook_path = hooks_dir / HOOK_NAME

    if hook_path.exists():
        existing = hook_path.read_text()
        if _MIGCARE_MARKER in existing:
            # Already installed — nothing to do.
            return hook_path
        # Append our block, preserving the user's existing hook.
        new_content = existing.rstrip("\n") + "\n\n" + _HOOK_BLOCK
    else:
        new_content = _HOOK_SHEBANG + _HOOK_BLOCK

    hook_path.write_text(new_content)
    hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return hook_path


def remove(project_root: Path) -> bool:
    """
    Remove the migcare block from the post-checkout hook.

    If the hook consisted entirely of the migcare block it is deleted.
    Returns True if anything was changed, False otherwise.
    """
    git_dir = _find_git_dir(project_root)
    if git_dir is None:
        return False

    hook_path = git_dir / "hooks" / HOOK_NAME
    if not hook_path.exists():
        return False

    content = hook_path.read_text()
    if _MIGCARE_MARKER not in content:
        return False

    # Strip the migcare block.  The block starts at the marker line and runs
    # to the end of _HOOK_TEMPLATE.
    stripped = _strip_migcare_block(content)
    if stripped.strip():
        hook_path.write_text(stripped)
    else:
        hook_path.unlink()
    return True


def _strip_migcare_block(content: str) -> str:
    """Remove the migcare-managed block (from _BLOCK_START to _BLOCK_END inclusive)."""
    start_idx = content.find(_BLOCK_START)
    if start_idx == -1:
        return content

    end_idx = content.find(_BLOCK_END, start_idx)
    if end_idx == -1:
        # Malformed — no end marker; strip everything from the start marker.
        cut = content[:start_idx].rstrip("\n")
        return (cut + "\n") if cut else ""

    # Include the newline that follows _BLOCK_END (if any).
    after_end = end_idx + len(_BLOCK_END)
    if after_end < len(content) and content[after_end] == "\n":
        after_end += 1

    before = content[:start_idx].rstrip("\n")
    after = content[after_end:].lstrip("\n")

    # If "before" is only the shebang line we prepended when creating a new
    # hook file, treat the file as fully owned by migcare and signal deletion.
    before_stripped = before.strip()
    before_is_only_shebang = before_stripped.startswith("#!") and "\n" not in before_stripped

    if before and not before_is_only_shebang and after:
        return before + "\n\n" + after
    elif before and not before_is_only_shebang:
        return before + "\n"
    elif after:
        return after
    else:
        return ""


def detect_ghost_migrations(prev_ref: str, new_ref: str) -> list[tuple[str, str]]:
    """
    Return a list of ``(app_label, migration_name)`` pairs that are recorded as
    applied in the DB but whose migration files are absent in the current
    working tree (i.e. after a branch switch).

    *prev_ref* and *new_ref* are git commit SHAs passed by the post-checkout
    hook; they are currently unused but kept for future diffing.
    """
    from django.db.migrations.recorder import MigrationRecorder

    applied = set(MigrationRecorder.Migration.objects.values_list("app", "name"))
    ghosts = []
    for app_label, migration_name in applied:
        if not _migration_file_exists(app_label, migration_name):
            ghosts.append((app_label, migration_name))
    return ghosts


def _migration_file_exists(app_label: str, migration_name: str) -> bool:
    """Return True if the migration module file can be found on disk."""
    from django.apps import apps

    try:
        app_config = apps.get_app_config(app_label)
    except LookupError:
        return False

    migrations_module = getattr(app_config.module, "__name__", app_label) + ".migrations"
    try:
        import importlib
        pkg = importlib.import_module(migrations_module)
        pkg_path = Path(pkg.__file__).parent  # type: ignore[arg-type]
    except (ImportError, TypeError, AttributeError):
        return False

    candidates = [
        pkg_path / f"{migration_name}.py",
        pkg_path / f"{migration_name}",
    ]
    return any(p.exists() for p in candidates)
