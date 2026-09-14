from __future__ import annotations

import datetime
import hashlib
import sys
from typing import Any


_CC_BODY_SKELETON: dict[str, Any] = {
    "memory": None,
    "taste": None,
    "skills": None,
    "permissionMode": "standard",
}

# The cmd CLI reports the session cwd as workingDir and its directory name as
# x-project-slug. The adapter forges a dev-machine project layout instead of
# leaking the container path, keeping both values consistent per slug.
_WORKSPACE_ROOT = "/home/dev/proj"
_DEFAULT_PROJECT_SLUG = "cc-adapter"

# Pool of plausible conventional-commit subjects for the forged recentCommits.
_COMMIT_SUBJECTS: tuple[str, ...] = (
    "feat: add streaming tool call support",
    "fix: handle empty upstream response",
    "refactor: split request and response translators",
    "chore: bump model registry",
    "test: cover tool result mapping",
    "docs: clarify environment variables",
    "perf: cache model lookups",
    "fix: retry once on transient upstream errors",
    "feat: expose model listing endpoint",
    "style: apply black formatting",
)


def _node_platform() -> str:
    """Platform string the cmd CLI reports as `environment` (Node process.platform)."""
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform in ("win32", "cygwin"):
        return "win32"
    return "linux"


def _utc_date() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


_STATIC_CONFIG: dict[str, Any] = {
    "environment": _node_platform(),
    "structure": ["src/", "tests/", "docs/"],
    "isGitRepo": True,
    "currentBranch": "main",
    "mainBranch": "main",
    "gitStatus": "Working tree clean",
}


def workspace_dir(project_slug: str) -> str:
    """Absolute forged workingDir for a project slug (basename == project_slug)."""
    return f"{_WORKSPACE_ROOT}/{project_slug}"


def recent_commits(project_slug: str) -> list[str]:
    """Three deterministic `<7 hex sha> <subject>` commits derived from the slug."""
    digest = hashlib.sha256(project_slug.encode("utf-8")).hexdigest()
    commits: list[str] = []
    for index in range(3):
        offset = index * 8
        short_hash = digest[offset : offset + 7]
        subject = _COMMIT_SUBJECTS[int(digest[offset + 7], 16) % len(_COMMIT_SUBJECTS)]
        commits.append(f"{short_hash} {subject}")
    return commits


def bind_workspace(config: dict[str, Any], project_slug: str) -> None:
    """Bind a CC body config to a workspace identity, in place.

    `project_slug` must be the same slug sent as the x-project-slug header so
    that workingDir and the header agree, like the real CLI.
    """
    config["workingDir"] = workspace_dir(project_slug)
    config["recentCommits"] = recent_commits(project_slug)


def make_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    base: dict[str, Any] = {
        "workingDir": workspace_dir(_DEFAULT_PROJECT_SLUG),
        "date": _utc_date(),
        **_STATIC_CONFIG,
        "structure": list(_STATIC_CONFIG["structure"]),
        "recentCommits": recent_commits(_DEFAULT_PROJECT_SLUG),
    }
    if overrides:
        base.update(overrides)
    return base


def make_cc_body(config: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    return {**_CC_BODY_SKELETON, "config": config, "params": params}
