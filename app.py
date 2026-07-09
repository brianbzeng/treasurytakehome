"""WSGI entry point for local development and Gunicorn."""

from treasury_app import create_app

app = create_app()
