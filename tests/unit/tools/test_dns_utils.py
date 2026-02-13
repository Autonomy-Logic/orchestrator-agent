import socket
from unittest.mock import patch, MagicMock

from tools.dns_utils import (
    parse_server_address,
    wait_for_dns,
    calculate_backoff,
    is_dns_error,
    perform_dns_health_check,
    RECONNECT_DELAY_BASE,
    RECONNECT_DELAY_MAX,
)


class TestParseServerAddress:
    def test_with_port(self):
        host, port = parse_server_address("api.getedge.me:8443")
        assert host == "api.getedge.me"
        assert port == 8443

    def test_no_port(self):
        host, port = parse_server_address("api.getedge.me")
        assert host == "api.getedge.me"
        assert port == 443

    def test_localhost(self):
        host, port = parse_server_address("localhost:3000")
        assert host == "localhost"
        assert port == 3000


class TestCalculateBackoff:
    def test_attempt_0(self):
        delay = calculate_backoff(0)
        # base * 2^0 = 1.0, with ±30% jitter: [0.7, 1.3], floored at base=1.0
        assert RECONNECT_DELAY_BASE <= delay <= 1.3

    def test_attempt_1(self):
        delay = calculate_backoff(1)
        # base * 2^1 = 2.0, with ±30% jitter: [1.4, 2.6], floored at base=1.0
        assert RECONNECT_DELAY_BASE <= delay <= 2.6

    def test_capped_at_max(self):
        delay = calculate_backoff(100)
        # Should not exceed max + jitter
        assert delay <= RECONNECT_DELAY_MAX * 1.3 + 0.01

    def test_always_above_base(self):
        for attempt in range(20):
            delay = calculate_backoff(attempt)
            assert delay >= RECONNECT_DELAY_BASE


class TestIsDnsError:
    def test_name_resolution(self):
        assert is_dns_error(Exception("name resolution failed")) is True

    def test_getaddrinfo(self):
        assert is_dns_error(Exception("getaddrinfo failed")) is True

    def test_nodename(self):
        assert is_dns_error(Exception("nodename nor servname provided")) is True

    def test_name_or_service(self):
        assert is_dns_error(Exception("Name or service not known")) is True

    def test_temporary_failure(self):
        assert is_dns_error(Exception("Temporary failure in name resolution")) is True

    def test_dns_keyword(self):
        assert is_dns_error(Exception("DNS lookup failed")) is True

    def test_not_dns_error(self):
        assert is_dns_error(Exception("Connection refused")) is False

    def test_timeout_not_dns(self):
        assert is_dns_error(Exception("Connection timed out")) is False


class TestPerformDnsHealthCheck:
    def test_skips_attempt_0(self):
        # Attempt 0 should return True immediately without any DNS check
        result = perform_dns_health_check("api.getedge.me:443", 0)
        assert result is True

    @patch("tools.dns_utils.wait_for_dns", return_value=True)
    def test_passes_on_successful_dns(self, mock_wait):
        result = perform_dns_health_check("api.getedge.me:443", 1)
        assert result is True
        mock_wait.assert_called_once_with("api.getedge.me", 443)

    @patch("tools.dns_utils.wait_for_dns", return_value=False)
    def test_fails_on_failed_dns(self, mock_wait):
        result = perform_dns_health_check("api.getedge.me:443", 1)
        assert result is False


class TestWaitForDns:
    @patch("tools.dns_utils.sleep")
    @patch("tools.dns_utils.socket")
    def test_success_on_first_try(self, mock_socket, mock_sleep):
        """DNS resolves on first attempt -> True."""
        mock_socket.AF_UNSPEC = socket.AF_UNSPEC
        mock_socket.SOCK_STREAM = socket.SOCK_STREAM
        mock_socket.AI_ADDRCONFIG = socket.AI_ADDRCONFIG
        mock_socket.gaierror = socket.gaierror
        mock_socket.getaddrinfo.return_value = [("family", "type", "proto", "canon", ("1.2.3.4", 443))]

        result = wait_for_dns("example.com", 443, max_retries=3)
        assert result is True
        mock_sleep.assert_not_called()

    @patch("tools.dns_utils.sleep")
    @patch("tools.dns_utils.socket")
    def test_gaierror_all_retries(self, mock_socket, mock_sleep):
        """DNS raises gaierror on every attempt -> False."""
        mock_socket.AF_UNSPEC = socket.AF_UNSPEC
        mock_socket.SOCK_STREAM = socket.SOCK_STREAM
        mock_socket.AI_ADDRCONFIG = socket.AI_ADDRCONFIG
        mock_socket.gaierror = socket.gaierror
        mock_socket.getaddrinfo.side_effect = socket.gaierror("Name resolution failed")

        result = wait_for_dns("bad.host", 443, max_retries=3)
        assert result is False

    @patch("tools.dns_utils.sleep")
    @patch("tools.dns_utils.socket")
    def test_generic_exception_all_retries(self, mock_socket, mock_sleep):
        """DNS raises generic Exception on every attempt -> False."""
        mock_socket.AF_UNSPEC = socket.AF_UNSPEC
        mock_socket.SOCK_STREAM = socket.SOCK_STREAM
        mock_socket.AI_ADDRCONFIG = socket.AI_ADDRCONFIG
        mock_socket.gaierror = socket.gaierror
        mock_socket.getaddrinfo.side_effect = OSError("network unreachable")

        result = wait_for_dns("bad.host", 443, max_retries=2)
        assert result is False

    @patch("tools.dns_utils.sleep")
    @patch("tools.dns_utils.socket")
    def test_gaierror_then_success(self, mock_socket, mock_sleep):
        """DNS fails first, succeeds second -> True."""
        mock_socket.AF_UNSPEC = socket.AF_UNSPEC
        mock_socket.SOCK_STREAM = socket.SOCK_STREAM
        mock_socket.AI_ADDRCONFIG = socket.AI_ADDRCONFIG
        mock_socket.gaierror = socket.gaierror
        mock_socket.getaddrinfo.side_effect = [
            socket.gaierror("fail"),
            [("family", "type", "proto", "canon", ("1.2.3.4", 443))],
        ]

        result = wait_for_dns("example.com", 443, max_retries=3)
        assert result is True

    @patch("tools.dns_utils.sleep")
    @patch("tools.dns_utils.socket")
    def test_empty_result(self, mock_socket, mock_sleep):
        """DNS returns empty list -> retries then False."""
        mock_socket.AF_UNSPEC = socket.AF_UNSPEC
        mock_socket.SOCK_STREAM = socket.SOCK_STREAM
        mock_socket.AI_ADDRCONFIG = socket.AI_ADDRCONFIG
        mock_socket.gaierror = socket.gaierror
        mock_socket.getaddrinfo.return_value = []

        result = wait_for_dns("example.com", 443, max_retries=1)
        assert result is False
