"""Compatibilidad de la configuración AWS."""

from .aws.config import KEYS, aws_options, load_settings

__all__ = ["KEYS", "aws_options", "load_settings"]
