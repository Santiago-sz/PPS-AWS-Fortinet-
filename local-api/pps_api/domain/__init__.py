"""Errores y precondiciones del dominio local."""


class Error(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code = status, code


def require(condition, code="invalid_request", status=400):
    if not condition:
        raise Error(status, code, code.replace("_", " "))
