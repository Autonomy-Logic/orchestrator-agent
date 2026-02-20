"""Shared fixtures for the orchestrator-agent test suite."""

import pytest

from tools.json_file import JsonConfigStore


@pytest.fixture
def tmp_json_file(tmp_path):
    """Return a path to a temporary JSON file."""
    return str(tmp_path / "test_config.json")


@pytest.fixture
def tmp_json_store(tmp_json_file):
    """Return a JsonConfigStore backed by a temporary file."""
    return JsonConfigStore(tmp_json_file)
