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
# leaking the container path, keeping both values consistent per slug. The home
# login is part of the forged identity too: every key serves its sessions from
# one forged machine, so workingDir is /home/<login>/proj/<slug>.
_DEFAULT_HOME_LOGIN = "dev"
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

# Pools for the forged per-project git/workspace metadata. Every value is a short
# plain string: these are interpolated into the upstream JSON body only, never
# into a shell or HTML.
#
# Top-level layout of the forged cwd. The default is the common case, the
# variants keep the directory names consistent with the other pools below.
_DEFAULT_STRUCTURE: tuple[str, ...] = ("src/", "tests/", "docs/")
_STRUCTURE_VARIANTS: tuple[tuple[str, ...], ...] = (
    ("app/", "tests/", "scripts/"),
    ("src/", "test/", "docs/"),
    ("lib/", "tests/", "examples/"),
)

# `gitStatus` is either the clean report or exactly one short `git status -s`
# entry (one line, no control characters - see the tests).
_CLEAN_GIT_STATUS = "Working tree clean"
_DIRTY_GIT_STATUS: tuple[str, ...] = (
    "M src/app.ts",
    "M src/index.ts",
    "?? notes.md",
    "M README.md",
    "?? src/.env.local",
    "M src/api/client.ts",
    "M config/settings.json",
    "?? scripts/seed.ts",
)

# Verb pool for the occasional `feature/<verb>-<slug word>` checked-out branch.
_FEATURE_VERBS: tuple[str, ...] = ("add", "fix", "refactor", "improve", "harden")

# Digest thresholds (raw sha256 bytes) - no randomness, no global state.
# digest[0] < 180, i.e. 180/256 ~= 70% (about 2/3 to 3/4) of all slugs, keeps the
# whole identity plain: "main", "Working tree clean" and the default structure.
# The remaining ~30% spread over the alternatives above; inside that share each
# field still keeps its plain value about half of the time.
_PLAIN_PROJECT_MIN = 180


def _node_platform() -> str:
    """Platform string the cmd CLI reports as `environment` (Node process.platform)."""
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform in ("win32", "cygwin"):
        return "win32"
    return "linux"


def _utc_date() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


# Default identity (make_config) - the plain values of the pools above. Only
# bind_workspace() varies them, per project slug.
_STATIC_CONFIG: dict[str, Any] = {
    "environment": _node_platform(),
    "structure": list(_DEFAULT_STRUCTURE),
    "isGitRepo": True,
    "currentBranch": "main",
    "mainBranch": "main",
    "gitStatus": _CLEAN_GIT_STATUS,
}


def workspace_root(home_login: str) -> str:
    """Forged project root of a home login (``/home/<login>/proj``)."""
    return f"/home/{home_login}/proj"


def workspace_dir(project_slug: str, home_login: str) -> str:
    """Absolute forged workingDir (basename == project_slug)."""
    return f"{workspace_root(home_login)}/{project_slug}"


def _slug_digest(project_slug: str) -> bytes:
    """Raw sha256 digest of a slug - a pure function of the slug, no state."""
    return hashlib.sha256(project_slug.encode("utf-8")).digest()


def recent_commits(project_slug: str) -> list[str]:
    """Three deterministic `<7 hex sha> <subject>` commits derived from the slug."""
    digest = _slug_digest(project_slug).hex()
    commits: list[str] = []
    for index in range(3):
        offset = index * 8
        short_hash = digest[offset : offset + 7]
        subject = _COMMIT_SUBJECTS[int(digest[offset + 7], 16) % len(_COMMIT_SUBJECTS)]
        commits.append(f"{short_hash} {subject}")
    return commits


def _slug_words(project_slug: str) -> list[str]:
    """Lowercase alphanumeric words of a slug, safe inside a branch name."""
    words: list[str] = []
    for chunk in project_slug.split("-"):
        word = "".join(ch for ch in chunk.lower() if "a" <= ch <= "z" or "0" <= ch <= "9")
        if word:
            words.append(word)
    return words


def _branch_names(project_slug: str, digest: bytes) -> tuple[str, str]:
    """Forge the checked-out branch of a slug that left `main`.

    Usually "develop", occasionally a feature branch built from the slug. The
    repository's main branch never moves: `mainBranch` stays "main" even when the
    working copy sits somewhere else.
    """
    if digest[1] % 3:
        return "develop", "main"
    words = _slug_words(project_slug) or ["work"]
    verb = _FEATURE_VERBS[digest[4] % len(_FEATURE_VERBS)]
    # Usually the whole slug (`feature/refactor-search-gateway`), sometimes just
    # its trailing word (`feature/add-caching`).
    tail = "-".join(words) if len(words) == 1 or digest[5] % 2 == 0 else words[-1]
    return f"feature/{verb}-{tail}", "main"


def workspace_metadata(project_slug: str) -> dict[str, Any]:
    """Forged git metadata of a slug, deterministic like `recent_commits`.

    About 70% of the slugs report the plain identity - "main"/"main"/clean tree/
    default structure, see `_PLAIN_PROJECT_MIN` - the rest vary one or more fields.
    `structure` is always a fresh list, never a shared object.
    """
    digest = _slug_digest(project_slug)
    if digest[0] < _PLAIN_PROJECT_MIN:
        return {
            "structure": list(_DEFAULT_STRUCTURE),
            "currentBranch": "main",
            "mainBranch": "main",
            "gitStatus": _CLEAN_GIT_STATUS,
        }
    current_branch, main_branch = _branch_names(project_slug, digest)
    structure = (
        list(_STRUCTURE_VARIANTS[digest[7] % len(_STRUCTURE_VARIANTS)])
        if digest[3] % 2 == 0
        else list(_DEFAULT_STRUCTURE)
    )
    git_status = _DIRTY_GIT_STATUS[digest[6] % len(_DIRTY_GIT_STATUS)] if digest[2] % 2 == 0 else _CLEAN_GIT_STATUS
    return {
        "structure": structure,
        "currentBranch": current_branch,
        "mainBranch": main_branch,
        "gitStatus": git_status,
    }


def bind_workspace(config: dict[str, Any], project_slug: str, home_login: str) -> None:
    """Bind a CC body config to a workspace identity, in place.

    `project_slug` must be the same slug sent as the x-project-slug header so
    that workingDir and the header agree, like the real CLI. The git metadata
    (branches, status, layout) follows the slug, so one (session, key) identity
    always describes the same repository state.
    """
    config["workingDir"] = workspace_dir(project_slug, home_login)
    config["recentCommits"] = recent_commits(project_slug)
    config.update(workspace_metadata(project_slug))


def make_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    base: dict[str, Any] = {
        "workingDir": workspace_dir(_DEFAULT_PROJECT_SLUG, _DEFAULT_HOME_LOGIN),
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
