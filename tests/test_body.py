"""Shape tests for the forged CC body (cc_adapter/command_code/body.py).

The expected values mirror real cmd CLI v1.54.0 /alpha/generate traffic.
"""

import datetime
import os
import re

import pytest

import cc_adapter.command_code.body as body_module
from cc_adapter.command_code.body import (
    _DEFAULT_HOME_LOGIN,
    _DEFAULT_PROJECT_SLUG,
    bind_workspace,
    make_cc_body,
    make_config,
    recent_commits,
    workspace_dir,
    workspace_metadata,
    workspace_root,
)

_NODE_PLATFORMS = ("linux", "darwin", "win32")

# Git/workspace pools documented in body.py: the forged config picks its
# structure/branches/gitStatus from these (see the digest thresholds there).
_PLAIN_BRANCH = "main"
_PLAIN_STRUCTURE = ["src/", "tests/", "docs/"]
_STRUCTURES = (
    ("src/", "tests/", "docs/"),
    ("app/", "tests/", "scripts/"),
    ("src/", "test/", "docs/"),
    ("lib/", "tests/", "examples/"),
)
_FEATURE_VERBS = ("add", "fix", "refactor", "improve", "harden")
_CLEAN_GIT_STATUS = "Working tree clean"
_DIRTY_GIT_STATUS = (
    "M src/app.ts",
    "M src/index.ts",
    "?? notes.md",
    "M README.md",
    "?? src/.env.local",
    "M src/api/client.ts",
    "M config/settings.json",
    "?? scripts/seed.ts",
)

# A fixed sample of the slugs the adapter actually serves, for the tests that
# need several identities at once.
_SAMPLE_SLUGS = (
    "alpha-services",
    "analytics-pipeline",
    "auth-gateway",
    "checkout-service",
    "core-api",
    "data-platform",
    "edge-runtime",
    "frontend-app",
    "infra-automation",
    "ml-training",
    "notification-hub",
    "payment-service",
    "search-indexer",
    "storage-layer",
    "user-portal",
    "video-pipeline",
    "api-monitor",
    "audit-service",
    "stream-processor",
    "partner-api",
)


def _slug_words(slug):
    return [word for word in re.split(r"[^a-z0-9]+", slug.lower()) if word]


def _assert_documented_metadata(metadata, slug):
    """Every derived value must come from the pools documented in body.py."""
    assert metadata["mainBranch"] == _PLAIN_BRANCH

    branch = metadata["currentBranch"]
    if branch not in (_PLAIN_BRANCH, "develop"):
        match = re.fullmatch(r"feature/([a-z]+)-([a-z0-9]+(?:-[a-z0-9]+)*)", branch)
        assert match, branch
        assert match.group(1) in _FEATURE_VERBS
        # the descriptive part of the branch name comes from the slug itself
        assert set(match.group(2).split("-")) <= set(_slug_words(slug))

    status = metadata["gitStatus"]
    assert status == _CLEAN_GIT_STATUS or status in _DIRTY_GIT_STATUS
    assert status and status == status.strip()  # one short line
    assert "\n" not in status and status.isprintable()  # no control characters

    structure = metadata["structure"]
    assert isinstance(structure, list)
    assert len(structure) == 3
    assert tuple(structure) in _STRUCTURES
    for entry in structure:
        assert isinstance(entry, str)
        assert entry.endswith("/") and 1 < len(entry) <= 24


def test_body_skeleton_matches_cmd_cli():
    """memory/taste/skills are JSON null for the CLI's default profile."""
    body = make_cc_body(config=make_config(), params={"model": "m"})
    assert body["memory"] is None
    assert body["taste"] is None
    assert body["skills"] is None
    assert body["permissionMode"] == "standard"


def test_config_matches_cmd_cli():
    config = make_config()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", config["date"])
    assert config["date"] == datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    assert config["environment"] in _NODE_PLATFORMS
    assert config["gitStatus"] == "Working tree clean"
    assert len(config["recentCommits"]) == 3
    # the CLI sends no additionalDirectories field
    assert "additionalDirectories" not in config


def test_node_platform_mapping(monkeypatch):
    """environment mirrors Node's process.platform for each sys.platform."""
    for platform, expected in (
        ("linux", "linux"),
        ("linux2", "linux"),
        ("darwin", "darwin"),
        ("win32", "win32"),
        ("cygwin", "win32"),
        ("freebsd12", "linux"),
    ):
        monkeypatch.setattr(body_module.sys, "platform", platform)
        assert body_module._node_platform() == expected


def test_recent_commits_shape():
    commits = recent_commits("alpha-services")
    assert len(commits) == 3
    for commit in commits:
        assert re.fullmatch(r"[0-9a-f]{7} \S.*", commit)


def test_bind_workspace_sets_working_dir_basename_to_slug():
    config = make_config()
    bind_workspace(config, "checkout-service", "mchen")
    assert config["workingDir"] == "/home/mchen/proj/checkout-service"
    assert os.path.basename(config["workingDir"]) == "checkout-service"
    assert config["recentCommits"] == recent_commits("checkout-service")


def test_workspace_dir_uses_the_home_login():
    # The forged cwd carries the key's home login, with the slug as its basename.
    assert workspace_root("priya") == "/home/priya/proj"
    assert workspace_dir("search-gateway", "priya") == "/home/priya/proj/search-gateway"
    assert workspace_dir("search-gateway", "dmitri") == "/home/dmitri/proj/search-gateway"


def test_bind_workspace_is_deterministic_per_slug():
    first: dict = {}
    second: dict = {}
    bind_workspace(first, "core-api", "alex")
    bind_workspace(second, "core-api", "alex")
    assert first["workingDir"] == second["workingDir"]
    assert first["recentCommits"] == second["recentCommits"]

    other: dict = {}
    bind_workspace(other, "data-platform", "alex")
    assert other["workingDir"] != first["workingDir"]
    assert other["recentCommits"] != first["recentCommits"]

    # Same project on another key's home login: only the home part changes.
    same_slug_other_login: dict = {}
    bind_workspace(same_slug_other_login, "core-api", "priya")
    assert same_slug_other_login["workingDir"] == "/home/priya/proj/core-api"
    assert same_slug_other_login["recentCommits"] == first["recentCommits"]


def test_make_config_default_working_dir_matches_workspace_dir():
    config = make_config()
    assert config["workingDir"] == workspace_dir(_DEFAULT_PROJECT_SLUG, _DEFAULT_HOME_LOGIN)
    assert config["workingDir"] == "/home/dev/proj/cc-adapter"  # unchanged default identity
    assert config["recentCommits"] == recent_commits(_DEFAULT_PROJECT_SLUG)


def test_make_config_overrides_win():
    config = make_config({"workingDir": "/tmp", "recentCommits": []})
    assert config["workingDir"] == "/tmp"
    assert config["recentCommits"] == []


def test_workspace_metadata_is_deterministic_per_slug():
    for slug in _SAMPLE_SLUGS:
        first = workspace_metadata(slug)
        second = workspace_metadata(slug)
        assert first["currentBranch"] == second["currentBranch"]
        assert first["mainBranch"] == second["mainBranch"]
        assert first["gitStatus"] == second["gitStatus"]
        assert first["structure"] == second["structure"]

    # The same project on two keys' home logins keeps one repository state.
    first_config: dict = {}
    second_config: dict = {}
    bind_workspace(first_config, "checkout-service", "mchen")
    bind_workspace(second_config, "checkout-service", "priya")
    assert first_config["workingDir"] != second_config["workingDir"]
    for key in ("currentBranch", "mainBranch", "gitStatus", "structure"):
        assert first_config[key] == second_config[key]


def test_workspace_metadata_returns_fresh_values():
    metadata = workspace_metadata("checkout-service")
    expected = list(metadata["structure"])
    metadata["structure"].append("junk/")
    assert workspace_metadata("checkout-service")["structure"] == expected

    # Neither the shared pool nor the static default identity leaks out as a
    # mutable object that a caller could corrupt for the whole process.
    assert workspace_metadata("checkout-service")["structure"] is not body_module._STATIC_CONFIG["structure"]

    first_config = make_config()
    second_config = make_config()
    bind_workspace(first_config, "checkout-service", "mchen")
    bind_workspace(second_config, "checkout-service", "priya")
    assert first_config["structure"] is not second_config["structure"]
    first_config["structure"].append("junk/")
    assert second_config["structure"] == expected


def _plain_identity(metadata):
    """True when a slug reports the common main + clean + default-structure case."""
    return (
        metadata["currentBranch"] == _PLAIN_BRANCH
        and metadata["gitStatus"] == _CLEAN_GIT_STATUS
        and metadata["structure"] == _PLAIN_STRUCTURE
    )


def test_workspace_metadata_varies_across_slugs():
    metadata = [workspace_metadata(slug) for slug in _SAMPLE_SLUGS]
    assert len({entry["currentBranch"] for entry in metadata}) >= 2
    assert len({tuple(entry["structure"]) for entry in metadata}) >= 2
    assert len({entry["gitStatus"] for entry in metadata}) >= 2
    # the plain identity is still the common case
    assert sum(1 for entry in metadata if _plain_identity(entry)) * 2 > len(metadata)


def test_workspace_metadata_plain_ratio_is_about_two_thirds_to_three_quarters():
    """~2/3 to 3/4 of the slugs keep main + clean tree + the default structure."""
    slugs = [f"proj-{index}" for index in range(2000)]
    plain = sum(1 for slug in slugs if _plain_identity(workspace_metadata(slug)))
    assert 2 / 3 <= plain / len(slugs) <= 3 / 4


def test_workspace_metadata_values_stay_in_the_documented_pools():
    for slug in list(_SAMPLE_SLUGS) + [f"proj-{index}" for index in range(64)]:
        metadata = workspace_metadata(slug)
        _assert_documented_metadata(metadata, slug)
        # whenever the checkout leaves main, mainBranch still reports main
        if metadata["currentBranch"] != metadata["mainBranch"]:
            assert metadata["mainBranch"] == _PLAIN_BRANCH


def test_bind_workspace_keeps_the_cc_body_complete():
    config = make_config()
    bind_workspace(config, "search-gateway", "priya")

    assert set(config) >= {
        "environment",
        "structure",
        "isGitRepo",
        "currentBranch",
        "mainBranch",
        "gitStatus",
        "workingDir",
        "recentCommits",
        "date",
    }
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", config["date"])
    assert config["environment"] in _NODE_PLATFORMS
    assert config["isGitRepo"] is True
    assert config["workingDir"] == "/home/priya/proj/search-gateway"
    assert config["recentCommits"] == recent_commits("search-gateway")
    assert isinstance(config["structure"], list) and len(config["structure"]) == 3

    body = make_cc_body(config=config, params={"model": "test", "messages": []})
    assert body["memory"] is None
    assert body["taste"] is None
    assert body["skills"] is None
    assert body["permissionMode"] == "standard"
    assert body["config"] is config


def test_make_config_default_identity_stays_plain():
    config = make_config()
    assert config["currentBranch"] == "main"
    assert config["mainBranch"] == "main"
    assert config["gitStatus"] == "Working tree clean"
    assert config["structure"] == ["src/", "tests/", "docs/"]
    assert config["workingDir"] == "/home/dev/proj/cc-adapter"
    assert config["recentCommits"] == recent_commits(_DEFAULT_PROJECT_SLUG)


def test_make_config_never_derives_the_per_slug_metadata(monkeypatch):
    """Only bind_workspace() varies the git metadata; make_config() stays static."""

    def explode(project_slug):
        raise AssertionError(f"unexpected per-slug derivation for {project_slug}")

    monkeypatch.setattr(body_module, "workspace_metadata", explode)

    config = make_config()
    assert config["currentBranch"] == "main"
    assert config["gitStatus"] == "Working tree clean"
    assert config["structure"] == ["src/", "tests/", "docs/"]

    with pytest.raises(AssertionError):
        bind_workspace(make_config(), "checkout-service", "mchen")
