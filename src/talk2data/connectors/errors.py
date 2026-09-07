"""Provider-neutral failures shared by query tools and connectors."""


class ConnectorValidationError(RuntimeError):
    """The approved plan cannot be executed safely."""


class SourceNotReadyError(RuntimeError):
    """Required data or coverage is unavailable; never switch sources automatically."""
