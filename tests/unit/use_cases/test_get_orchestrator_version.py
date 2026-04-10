import pytest
from unittest.mock import MagicMock, patch

from use_cases.get_orchestrator_version import (
    get_orchestrator_version,
    NETMON_CONTAINER_NAME,
)


class _NotFoundError(Exception):
    pass


def _make_runtime():
    mock_runtime = MagicMock()
    mock_runtime.NotFoundError = _NotFoundError
    return mock_runtime


class TestGetOrchestratorVersion:
    @patch.dict("os.environ", {"AGENT_VERSION": "v1.2.3", "HOSTNAME": "abc123"})
    def test_returns_all_version_info(self):
        """Returns orchestrator version, netmon version, and image ID."""
        runtime = _make_runtime()

        # Mock netmon container with AGENT_VERSION env
        netmon = MagicMock()
        netmon.attrs = {"Config": {"Env": ["PATH=/usr/bin", "AGENT_VERSION=v1.2.3"]}}

        # Mock self container
        self_container = MagicMock()
        self_container.image.id = "sha256:deadbeef"

        def get_container(name):
            if name == NETMON_CONTAINER_NAME:
                return netmon
            if name == "abc123":
                return self_container
            raise _NotFoundError()

        runtime.get_container.side_effect = get_container

        result = get_orchestrator_version(container_runtime=runtime)

        assert result["orchestrator_version"] == "v1.2.3"
        assert result["netmon_version"] == "v1.2.3"
        assert result["orchestrator_image_id"] == "sha256:deadbeef"

    @patch.dict("os.environ", {"AGENT_VERSION": "v1.0.0", "HOSTNAME": ""})
    def test_netmon_not_found(self):
        """Returns 'unknown' for netmon if container not found."""
        runtime = _make_runtime()
        runtime.get_container.side_effect = _NotFoundError()

        result = get_orchestrator_version(container_runtime=runtime)

        assert result["orchestrator_version"] == "v1.0.0"
        assert result["netmon_version"] == "unknown"

    @patch.dict("os.environ", {}, clear=True)
    def test_no_env_vars(self):
        """Returns 'unknown' when AGENT_VERSION is not set."""
        runtime = _make_runtime()
        runtime.get_container.side_effect = _NotFoundError()

        result = get_orchestrator_version(container_runtime=runtime)

        assert result["orchestrator_version"] == "unknown"
        assert result["netmon_version"] == "unknown"
        assert result["orchestrator_image_id"] == "unknown"

    @patch.dict("os.environ", {"AGENT_VERSION": "v2.0.0", "HOSTNAME": "abc123"})
    def test_netmon_without_version_env(self):
        """Returns 'unknown' if netmon container has no AGENT_VERSION env."""
        runtime = _make_runtime()

        netmon = MagicMock()
        netmon.attrs = {"Config": {"Env": ["PATH=/usr/bin"]}}

        self_container = MagicMock()
        self_container.image.id = "sha256:abc"

        def get_container(name):
            if name == NETMON_CONTAINER_NAME:
                return netmon
            if name == "abc123":
                return self_container
            raise _NotFoundError()

        runtime.get_container.side_effect = get_container

        result = get_orchestrator_version(container_runtime=runtime)

        assert result["orchestrator_version"] == "v2.0.0"
        assert result["netmon_version"] == "unknown"
