import pytest
from unittest.mock import MagicMock

from tools.contract_validation import (
    BaseType,
    StringType,
    NonEmptyStringType,
    InterfaceNameType,
    NumberType,
    BooleanType,
    DateType,
    ListType,
    OptionalType,
    ContractValidationError,
    validate_contract,
    validate_contract_with_error_response,
    BASE_MESSAGE,
    BASE_DEVICE,
)


# --- Type Validators ---


class TestStringType:
    def test_valid(self):
        StringType.validate("hello")
        StringType.validate("")

    def test_invalid_int(self):
        with pytest.raises(TypeError):
            StringType.validate(123)

    def test_invalid_none(self):
        with pytest.raises(TypeError):
            StringType.validate(None)

    def test_invalid_bool(self):
        with pytest.raises(TypeError):
            StringType.validate(True)


class TestNonEmptyStringType:
    def test_valid(self):
        NonEmptyStringType.validate("hello")

    def test_rejects_empty(self):
        with pytest.raises(TypeError):
            NonEmptyStringType.validate("")

    def test_rejects_whitespace(self):
        with pytest.raises(TypeError):
            NonEmptyStringType.validate("   ")

    def test_rejects_non_string(self):
        with pytest.raises(TypeError):
            NonEmptyStringType.validate(42)


class TestNumberType:
    def test_valid_int(self):
        NumberType.validate(42)

    def test_valid_float(self):
        NumberType.validate(3.14)

    def test_invalid_string(self):
        with pytest.raises(TypeError):
            NumberType.validate("42")

    def test_invalid_none(self):
        with pytest.raises(TypeError):
            NumberType.validate(None)


class TestBooleanType:
    def test_valid_true(self):
        BooleanType.validate(True)

    def test_valid_false(self):
        BooleanType.validate(False)

    def test_invalid_int_0(self):
        with pytest.raises(TypeError):
            BooleanType.validate(0)

    def test_invalid_int_1(self):
        with pytest.raises(TypeError):
            BooleanType.validate(1)

    def test_invalid_string(self):
        with pytest.raises(TypeError):
            BooleanType.validate("true")


class TestDateType:
    def test_valid_iso(self):
        DateType.validate("2024-01-15T10:30:00")

    def test_valid_z_suffix(self):
        DateType.validate("2024-01-15T10:30:00Z")

    def test_valid_with_offset(self):
        DateType.validate("2024-01-15T10:30:00+05:30")

    def test_invalid_format(self):
        with pytest.raises(TypeError):
            DateType.validate("not-a-date")

    def test_invalid_non_string(self):
        with pytest.raises(TypeError):
            DateType.validate(12345)


# --- Composite Types ---


class TestListType:
    def test_valid(self):
        lt = ListType(StringType)
        lt.validate(["a", "b", "c"])

    def test_empty_list(self):
        lt = ListType(StringType)
        lt.validate([])

    def test_not_a_list(self):
        lt = ListType(StringType)
        with pytest.raises(TypeError):
            lt.validate("not a list")

    def test_invalid_item(self):
        lt = ListType(StringType)
        with pytest.raises(TypeError):
            lt.validate(["a", 123, "c"])

    def test_nested_schema(self):
        lt = ListType({"name": StringType, "age": NumberType})
        lt.validate([{"name": "Alice", "age": 30}])

    def test_nested_schema_invalid(self):
        lt = ListType({"name": StringType})
        with pytest.raises(TypeError):
            lt.validate([{"name": 123}])


class TestOptionalType:
    def test_none_passes(self):
        ot = OptionalType(StringType)
        ot.validate(None)

    def test_valid_value(self):
        ot = OptionalType(NumberType)
        ot.validate(42)

    def test_invalid_value(self):
        ot = OptionalType(NumberType)
        with pytest.raises(TypeError):
            ot.validate("not a number")


# --- validate_contract ---


class TestValidateContract:
    def test_valid_contract(self):
        schema = {"name": StringType, "age": NumberType}
        validate_contract(schema, {"name": "Alice", "age": 30})

    def test_missing_required_key(self):
        schema = {"name": StringType, "age": NumberType}
        with pytest.raises(KeyError):
            validate_contract(schema, {"name": "Alice"})

    def test_type_mismatch(self):
        schema = {"name": StringType}
        with pytest.raises(TypeError):
            validate_contract(schema, {"name": 42})

    def test_nested_schema(self):
        schema = {"address": {"city": StringType, "zip": StringType}}
        validate_contract(schema, {"address": {"city": "NYC", "zip": "10001"}})

    def test_optional_key_missing_passes(self):
        schema = {"name": StringType, "age": OptionalType(NumberType)}
        validate_contract(schema, {"name": "Alice"})

    def test_optional_key_present_validates(self):
        schema = {"name": StringType, "age": OptionalType(NumberType)}
        with pytest.raises(TypeError):
            validate_contract(schema, {"name": "Alice", "age": "not a number"})

    def test_extra_keys_ignored(self):
        schema = {"name": StringType}
        validate_contract(schema, {"name": "Alice", "extra": "ignored"})


# --- validate_contract_with_error_response ---


class TestValidateContractWithErrorResponse:
    def test_valid_returns_true(self):
        schema = {"name": StringType}
        is_valid, error = validate_contract_with_error_response(
            schema, {"name": "Alice"}
        )
        assert is_valid is True
        assert error is None

    def test_missing_key_returns_error(self):
        schema = {"name": StringType, "age": NumberType}
        is_valid, error = validate_contract_with_error_response(
            schema, {"name": "Alice"}
        )
        assert is_valid is False
        assert error["status"] == "error"
        assert "Missing required field" in error["error"]

    def test_type_error_returns_error(self):
        schema = {"name": StringType}
        is_valid, error = validate_contract_with_error_response(
            schema, {"name": 42}
        )
        assert is_valid is False
        assert error["status"] == "error"
        assert "Invalid field type" in error["error"]


# --- Schema Constants ---


class TestSchemaConstants:
    def test_base_message_all_optional(self):
        # BASE_MESSAGE fields are all optional, so empty dict should pass
        validate_contract(BASE_MESSAGE, {})

    def test_base_message_with_values(self):
        validate_contract(
            BASE_MESSAGE,
            {
                "correlation_id": 123,
                "action": "test",
                "requested_at": "2024-01-15T10:30:00Z",
            },
        )

    def test_base_device_requires_non_empty_device_id(self):
        with pytest.raises(KeyError):
            validate_contract(BASE_DEVICE, {})

    def test_base_device_rejects_empty_device_id(self):
        with pytest.raises(TypeError):
            validate_contract(BASE_DEVICE, {"device_id": ""})

    def test_base_device_valid(self):
        validate_contract(BASE_DEVICE, {"device_id": "my-device-001"})


# --- BaseType ---


class TestBaseType:
    def test_cannot_instantiate(self):
        with pytest.raises(Exception, match="Cannot instantiate"):
            BaseType()

    def test_validate_raises_not_implemented(self):
        with pytest.raises(NotImplementedError):
            BaseType.validate()


# --- ContractValidationError ---


class TestContractValidationError:
    def test_stores_fields(self):
        err = ContractValidationError("type_err", "bad value")
        assert err.error_type == "type_err"
        assert err.message == "bad value"
        assert str(err) == "bad value"


# --- Generic Exception in validate_contract_with_error_response ---


class TestValidateContractGenericException:
    def test_generic_exception_returns_error(self):
        """Line 163-165: catch non-KeyError/TypeError Exception."""
        # Create a mock type whose validate() raises ValueError
        bad_type = MagicMock()
        bad_type.validate.side_effect = ValueError("something went wrong")

        schema = {"field": bad_type}
        is_valid, error = validate_contract_with_error_response(
            schema, {"field": "anything"}
        )
        assert is_valid is False
        assert error["status"] == "error"
        assert "Validation error" in error["error"]
        assert "something went wrong" in error["error"]


class TestInterfaceNameType:
    def test_valid_simple(self):
        InterfaceNameType.validate("eth0")

    def test_valid_with_dots_dashes_underscores(self):
        InterfaceNameType.validate("wlan0.1")
        InterfaceNameType.validate("br-lan")
        InterfaceNameType.validate("veth_abc")

    def test_valid_max_length(self):
        InterfaceNameType.validate("a" * 15)

    def test_invalid_not_string(self):
        with pytest.raises(TypeError, match="must be a string"):
            InterfaceNameType.validate(123)

    def test_invalid_empty(self):
        with pytest.raises(TypeError, match="valid Linux interface name"):
            InterfaceNameType.validate("")

    def test_invalid_too_long(self):
        with pytest.raises(TypeError, match="valid Linux interface name"):
            InterfaceNameType.validate("a" * 16)

    def test_invalid_special_chars(self):
        with pytest.raises(TypeError, match="valid Linux interface name"):
            InterfaceNameType.validate("eth0/foo")
