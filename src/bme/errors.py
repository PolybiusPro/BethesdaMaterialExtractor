class BmeError(Exception):
    """Base class for errors that can be presented directly to a user."""


class FormatError(BmeError):
    """Raised when an input is not a supported or valid binary format."""


class MissingMaterialError(BmeError):
    """Raised when a requested material is absent from the database."""
