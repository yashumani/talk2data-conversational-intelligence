"""Private API entry point; explicit private configuration and ADC are required."""

from talk2data.internal.bootstrap import create_internal_app

app = create_internal_app()
