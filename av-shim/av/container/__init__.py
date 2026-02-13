class Container:
    """Stub container."""

    def __init__(self):
        raise NotImplementedError("av shim: real PyAV is not available on this platform")


class InputContainer(Container):
    """Stub input container."""
    pass


class OutputContainer(Container):
    """Stub output container."""
    pass


def open(*args, **kwargs):
    raise NotImplementedError("av shim: real PyAV is not available on this platform")
