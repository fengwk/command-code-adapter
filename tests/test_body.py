"""Shape tests for the forged CC body (cc_adapter/command_code/body.py).

The expected values mirror real cmd CLI v1.54.0 /alpha/generate traffic.
"""

import datetime
import os
import re

import cc_adapter.command_code.body as body_module
from cc_adapter.command_code.body import (
    _WORKSPACE_ROOT,
    bind_workspace,
    make_cc_body,
    make_config,
    recent_commits,
    workspace_dir,
)

_NODE_PLATFORMS = ("linux", "darwin", "win32")


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
    bind_workspace(config, "checkout-service")
    assert config["workingDir"] == f"{_WORKSPACE_ROOT}/checkout-service"
    assert os.path.basename(config["workingDir"]) == "checkout-service"
    assert config["recentCommits"] == recent_commits("checkout-service")


def test_bind_workspace_is_deterministic_per_slug():
    first: dict = {}
    second: dict = {}
    bind_workspace(first, "core-api")
    bind_workspace(second, "core-api")
    assert first["workingDir"] == second["workingDir"]
    assert first["recentCommits"] == second["recentCommits"]

    other: dict = {}
    bind_workspace(other, "data-platform")
    assert other["workingDir"] != first["workingDir"]
    assert other["recentCommits"] != first["recentCommits"]


def test_make_config_default_working_dir_matches_workspace_dir():
    config = make_config()
    assert config["workingDir"] == workspace_dir(body_module._DEFAULT_PROJECT_SLUG)
    assert config["recentCommits"] == recent_commits(body_module._DEFAULT_PROJECT_SLUG)


def test_make_config_overrides_win():
    config = make_config({"workingDir": "/tmp", "recentCommits": []})
    assert config["workingDir"] == "/tmp"
    assert config["recentCommits"] == []
