from novelwiki.kernel.errors import ApplicationError


class AudioFileGone(ApplicationError):
    """The cache row exists but its audio file is no longer present."""

