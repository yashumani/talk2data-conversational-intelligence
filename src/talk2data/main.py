"""ASGI entry point. Provider and connector setup lives outside this module."""

from talk2data.bootstrap import create_app

__all__ = ["app", "create_app"]

app = create_app()
