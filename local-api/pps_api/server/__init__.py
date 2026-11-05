"""Adaptador HTTP/HTTPS local, sin clientes AWS."""

from .app import create_server

__all__ = ["create_server"]
