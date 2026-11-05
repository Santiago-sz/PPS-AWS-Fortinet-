"""Compatibilidad de imports; implementación en services/policies.py."""

from .services.policies import MAX_UPLOAD, MIMES, Error, Service, require

__all__ = ["MAX_UPLOAD", "MIMES", "Error", "Service", "require"]
