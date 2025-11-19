from datetime import datetime


class BaseType:

    def __init__(self):
        raise Exception("Cannot instantiate")

    @staticmethod
    def validate():
        raise NotImplementedError("Subclasses should implement this!")


class NumberType(BaseType):

    @staticmethod
    def validate(value):
        if not isinstance(value, (int, float)):
            raise TypeError("Value must be a number.")


class StringType(BaseType):

    @staticmethod
    def validate(value):
        if not isinstance(value, str):
            raise TypeError("Value must be a string.")


class DateType(BaseType):

    @staticmethod
    def validate(value):
        try:
            if not isinstance(value, str):
                raise TypeError()
            if value.endswith('Z'):
                value = value.replace('Z', '+00:00')
            datetime.fromisoformat(value)
        except (TypeError, ValueError):
            raise TypeError("Value must be a valid ISO datetime string.")


class BooleanType(BaseType):

    @staticmethod
    def validate(value):
        if not isinstance(value, bool):
            raise TypeError("Value must be a boolean.")


class ListType(BaseType):

    def __init__(self, item_type):
        self.item_type = item_type

    def validate(self, value):

        if not isinstance(value, list):
            raise TypeError("Value must be a list.")

        for item in value:
            if isinstance(self.item_type, dict):
                validate_contract(self.item_type, item)
            else:
                self.item_type.validate(item)


class OptionalType(BaseType):

    def __init__(self, item_type):
        self.item_type = item_type

    def validate(self, value):
        if value is not None:
            self.item_type.validate(value)


BASE_MESSAGE = {
    "correlation_id": NumberType,
    "action": StringType,
    "requested_at": DateType,
}

BASE_DEVICE = {**BASE_MESSAGE, "device_id": StringType}


def validate_contract(contract, data):
    for key, value in contract.items():
        if key not in data:
            if isinstance(value, OptionalType):
                continue
            raise KeyError(f"Missing key: {key}")
        if isinstance(value, dict):
            validate_contract(value, data[key])
        else:
            value.validate(data[key])
