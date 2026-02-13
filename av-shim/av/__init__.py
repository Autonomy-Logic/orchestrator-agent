from .frame import Frame
from .packet import Packet
from .audio.frame import AudioFrame
from .video.frame import VideoFrame, PictureType
from . import audio, video, codec, container


class FFmpegError(Exception):
    pass


def open(*args, **kwargs):
    return container.open(*args, **kwargs)
