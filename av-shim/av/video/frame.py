import enum

from av.frame import Frame


class PictureType(enum.IntEnum):
    NONE = 0
    I = 1


class VideoFrame(Frame):
    """Stub video frame."""
    pass
