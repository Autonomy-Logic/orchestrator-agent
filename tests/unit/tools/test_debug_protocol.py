"""Tests for tools.debug_protocol — protocol constants, builders, and parsers."""

import pytest

from tools.debug_protocol import (
    # Constants
    FC_DEBUG_INFO,
    FC_DEBUG_SET,
    FC_DEBUG_GET,
    FC_DEBUG_GET_LIST,
    FC_DEBUG_GET_MD5,
    STATUS_SUCCESS,
    STATUS_OUT_OF_BOUNDS,
    STATUS_OUT_OF_MEMORY,
    # Helpers
    bytes_to_hex,
    hex_to_bytes,
    status_name,
    fc_name,
    # Builders
    build_get_md5,
    build_get_info,
    build_get_list,
    build_set_variable,
    # Parser
    parse_response,
)


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


class TestBytesToHex:
    def test_empty(self):
        assert bytes_to_hex(b"") == ""

    def test_single_byte(self):
        assert bytes_to_hex(b"\x41") == "41"

    def test_multiple_bytes(self):
        assert bytes_to_hex(b"\x45\xDE\xAD\x00\x00") == "45 DE AD 00 00"

    def test_leading_zeros_preserved(self):
        assert bytes_to_hex(b"\x00\x01\x0A") == "00 01 0A"

    def test_all_ff(self):
        assert bytes_to_hex(b"\xFF\xFF") == "FF FF"


class TestHexToBytes:
    def test_empty(self):
        assert hex_to_bytes("") == b""

    def test_single_byte(self):
        assert hex_to_bytes("41") == b"\x41"

    def test_space_separated(self):
        assert hex_to_bytes("45 DE AD 00 00") == b"\x45\xDE\xAD\x00\x00"

    def test_no_spaces(self):
        assert hex_to_bytes("45DEAD0000") == b"\x45\xDE\xAD\x00\x00"

    def test_lowercase(self):
        assert hex_to_bytes("de ad") == b"\xDE\xAD"


class TestRoundtrip:
    def test_bytes_to_hex_to_bytes(self):
        original = b"\x44\x7E\x00\x02\x00\x00\x00\x42\x00\x03\x01\x02\x03"
        assert hex_to_bytes(bytes_to_hex(original)) == original

    def test_hex_to_bytes_to_hex(self):
        original = "44 7E 00 02 00 00 00 42 00 03 01 02 03"
        assert bytes_to_hex(hex_to_bytes(original)) == original


class TestStatusName:
    def test_success(self):
        assert status_name(STATUS_SUCCESS) == "SUCCESS"

    def test_out_of_bounds(self):
        assert status_name(STATUS_OUT_OF_BOUNDS) == "ERROR_OUT_OF_BOUNDS"

    def test_out_of_memory(self):
        assert status_name(STATUS_OUT_OF_MEMORY) == "ERROR_OUT_OF_MEMORY"

    def test_unknown(self):
        assert status_name(0xFF) == "UNKNOWN(0xFF)"


class TestFcName:
    def test_all_known(self):
        assert fc_name(FC_DEBUG_INFO) == "DEBUG_INFO"
        assert fc_name(FC_DEBUG_SET) == "DEBUG_SET"
        assert fc_name(FC_DEBUG_GET) == "DEBUG_GET"
        assert fc_name(FC_DEBUG_GET_LIST) == "DEBUG_GET_LIST"
        assert fc_name(FC_DEBUG_GET_MD5) == "DEBUG_GET_MD5"

    def test_unknown(self):
        assert fc_name(0x99) == "UNKNOWN(0x99)"


# ---------------------------------------------------------------------------
# Command builders
# ---------------------------------------------------------------------------


class TestBuildGetMd5:
    def test_format(self):
        result = build_get_md5()
        assert result == "45 DE AD 00 00"

    def test_length(self):
        data = hex_to_bytes(build_get_md5())
        assert len(data) == 5

    def test_function_code(self):
        data = hex_to_bytes(build_get_md5())
        assert data[0] == FC_DEBUG_GET_MD5

    def test_endianness_check(self):
        data = hex_to_bytes(build_get_md5())
        assert data[1] == 0xDE
        assert data[2] == 0xAD


class TestBuildGetInfo:
    def test_format(self):
        assert build_get_info() == "41"

    def test_length(self):
        data = hex_to_bytes(build_get_info())
        assert len(data) == 1

    def test_function_code(self):
        data = hex_to_bytes(build_get_info())
        assert data[0] == FC_DEBUG_INFO


class TestBuildGetList:
    def test_single_index(self):
        result = build_get_list([0])
        assert result == "44 00 01 00 00"

    def test_three_indexes(self):
        result = build_get_list([0, 1, 2])
        assert result == "44 00 03 00 00 00 01 00 02"

    def test_high_index(self):
        result = build_get_list([255])
        assert result == "44 00 01 00 FF"

    def test_function_code(self):
        data = hex_to_bytes(build_get_list([5]))
        assert data[0] == FC_DEBUG_GET_LIST

    def test_count_field(self):
        data = hex_to_bytes(build_get_list([0, 1, 2]))
        count = (data[1] << 8) | data[2]
        assert count == 3

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            build_get_list([])

    def test_too_many_raises(self):
        with pytest.raises(ValueError, match="must not exceed 256"):
            build_get_list(list(range(257)))

    def test_max_256_ok(self):
        result = build_get_list(list(range(256)))
        data = hex_to_bytes(result)
        count = (data[1] << 8) | data[2]
        assert count == 256


class TestBuildSetVariable:
    def test_force_int(self):
        result = build_set_variable(5, True, b"\x2A\x00")
        assert result == "42 00 05 01 00 02 2A 00"

    def test_release(self):
        result = build_set_variable(5, False, b"\x00")
        assert result == "42 00 05 00 00 01 00"

    def test_function_code(self):
        data = hex_to_bytes(build_set_variable(0, True, b"\x01"))
        assert data[0] == FC_DEBUG_SET

    def test_index_field(self):
        data = hex_to_bytes(build_set_variable(10, True, b"\x01"))
        index = (data[1] << 8) | data[2]
        assert index == 10

    def test_force_flag(self):
        data_force = hex_to_bytes(build_set_variable(0, True, b"\x01"))
        data_release = hex_to_bytes(build_set_variable(0, False, b"\x01"))
        assert data_force[3] == 1
        assert data_release[3] == 0

    def test_data_length_field(self):
        value = b"\x01\x02\x03\x04"
        data = hex_to_bytes(build_set_variable(0, True, value))
        length = (data[4] << 8) | data[5]
        assert length == 4

    def test_value_bytes_appended(self):
        value = b"\xAB\xCD"
        data = hex_to_bytes(build_set_variable(0, True, value))
        assert data[6:] == value


# ---------------------------------------------------------------------------
# Response parsers
# ---------------------------------------------------------------------------


class TestParseResponseMalformedHex:
    def test_invalid_hex_characters(self):
        result = parse_response("ZZ GG")
        assert result["function_code"] is None
        assert "malformed hex" in result["error"]
        assert result["raw"] == "ZZ GG"

    def test_odd_length_hex(self):
        result = parse_response("4")
        assert result["function_code"] is None
        assert "malformed hex" in result["error"]


class TestParseResponseEmpty:
    def test_empty_string(self):
        result = parse_response("")
        assert result["function_code"] is None
        assert "empty" in result["error"]


class TestParseResponseUnknown:
    def test_unknown_function_code(self):
        result = parse_response("99 01 02")
        assert result["function_code"] == 0x99
        assert "unknown" in result["error"]
        assert result["raw"] == "99 01 02"


class TestParseInfoResponse:
    def test_valid_five_variables(self):
        result = parse_response("41 00 05")
        assert result["function_code"] == FC_DEBUG_INFO
        assert result["function_name"] == "DEBUG_INFO"
        assert result["variable_count"] == 5

    def test_zero_variables(self):
        result = parse_response("41 00 00")
        assert result["variable_count"] == 0

    def test_large_count(self):
        result = parse_response("41 01 00")
        assert result["variable_count"] == 256

    def test_too_short(self):
        result = parse_response("41")
        assert "error" in result
        assert "too short" in result["error"]

    def test_raw_preserved(self):
        result = parse_response("41 00 05")
        assert result["raw"] == "41 00 05"


class TestParseSetResponse:
    def test_success(self):
        result = parse_response("42 7E")
        assert result["function_code"] == FC_DEBUG_SET
        assert result["status"] == STATUS_SUCCESS
        assert result["status_name"] == "SUCCESS"

    def test_out_of_bounds(self):
        result = parse_response("42 81")
        assert result["status"] == STATUS_OUT_OF_BOUNDS
        assert result["status_name"] == "ERROR_OUT_OF_BOUNDS"

    def test_too_short(self):
        result = parse_response("42")
        assert "error" in result
        assert "too short" in result["error"]


class TestParseGetMd5Response:
    def test_success_with_md5(self):
        # "45 7E" + ASCII "abcdef" (61 62 63 64 65 66)
        result = parse_response("45 7E 61 62 63 64 65 66")
        assert result["function_code"] == FC_DEBUG_GET_MD5
        assert result["status"] == STATUS_SUCCESS
        assert result["md5"] == "abcdef"

    def test_md5_with_null_terminator(self):
        # "45 7E" + "abc" + null + garbage
        result = parse_response("45 7E 61 62 63 00 FF FF")
        assert result["md5"] == "abc"

    def test_status_only_no_md5(self):
        result = parse_response("45 7E")
        assert result["status"] == STATUS_SUCCESS
        assert "md5" not in result

    def test_error_status(self):
        result = parse_response("45 81")
        assert result["status"] == STATUS_OUT_OF_BOUNDS

    def test_too_short(self):
        result = parse_response("45")
        assert "error" in result


class TestParseGetListResponse:
    def test_success_with_data(self):
        # fc=44, status=7E, last_idx=0002, tick=00000042, data_size=0003, data=010203
        result = parse_response("44 7E 00 02 00 00 00 42 00 03 01 02 03")
        assert result["function_code"] == FC_DEBUG_GET_LIST
        assert result["status"] == STATUS_SUCCESS
        assert result["last_index"] == 2
        assert result["tick"] == 66
        assert result["data_size"] == 3
        assert result["variable_data_hex"] == "01 02 03"

    def test_success_no_variable_data(self):
        # fc=44, status=7E, last_idx=0000, tick=00000000, data_size=0000
        result = parse_response("44 7E 00 00 00 00 00 00 00 00")
        assert result["data_size"] == 0
        assert result["variable_data_hex"] == ""

    def test_error_out_of_bounds(self):
        result = parse_response("44 81")
        assert result["status"] == STATUS_OUT_OF_BOUNDS
        assert "last_index" not in result

    def test_success_but_too_short(self):
        # Status is success but header is incomplete
        result = parse_response("44 7E 00 02")
        assert "error" in result
        assert "too short" in result["error"]

    def test_get_fc_also_parsed(self):
        # FC_DEBUG_GET (0x43) uses the same parser
        result = parse_response("43 7E 00 01 00 00 00 01 00 02 AB CD")
        assert result["function_code"] == FC_DEBUG_GET
        assert result["last_index"] == 1
        assert result["tick"] == 1
        assert result["data_size"] == 2
        assert result["variable_data_hex"] == "AB CD"

    def test_truncated_variable_data(self):
        # Header says data_size=5 but only 2 bytes of var data present
        result = parse_response("44 7E 00 02 00 00 00 42 00 05 01 02")
        assert "truncated" in result["error"]

    def test_too_short_for_any_parse(self):
        result = parse_response("44")
        assert "error" in result
