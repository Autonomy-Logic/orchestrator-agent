from datetime import datetime


class BaseType:

    def __init__(self):
        raise Exception("Cannot instantiate")

    def validate():
        raise NotImplementedError("Subclasses should implement this!")


class NumberType(BaseType):

    def validate(value):
        if not isinstance(value, (int, float)):
            raise TypeError("Value must be a number.")


class StringType(BaseType):

    def validate(value):
        if not isinstance(value, str):
            raise TypeError("Value must be a string.")


class DateType(BaseType):

    def validate(value):
        try:
            datetime.fromisoformat(value)
        except (TypeError, ValueError):
            raise TypeError("Value must be a valid ISO datetime string.")


class BooleanType(BaseType):

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
            self.item_type.validate(item)


def validate_contract(contract, data):
    for key, value in contract.items():
        if key not in data:
            raise KeyError(f"Missing key: {key}")
        if isinstance(value, dict):
            validate_contract(value, data[key])
        else:
            value.validate(data[key])
