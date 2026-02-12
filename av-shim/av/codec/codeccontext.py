class CodecContext:
    """Stub codec context base class."""

    @classmethod
    def create(cls, *args, **kwargs):
        raise NotImplementedError("av shim: real PyAV is not available on this platform")

    def __init__(self):
        raise NotImplementedError("av shim: real PyAV is not available on this platform")
