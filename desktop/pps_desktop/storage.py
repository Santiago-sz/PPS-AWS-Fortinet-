"""Encrypted, expiring cache; no silent plaintext fallback."""

import hashlib
import json
from pathlib import Path
import time

from cryptography.fernet import Fernet, InvalidToken
import keyring


class SecureCache:
    def __init__(self, root, identity, ttl=86400, key=None, clock=time.time):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.scope = hashlib.sha256(identity.encode()).hexdigest()
        self.path = self.root / (self.scope + ".enc")
        self.ttl = ttl
        self.clock = clock
        if key is None:
            # Use only OS credential stores (never keyrings.alt/plaintext).
            backend = keyring.get_keyring()
            module = type(backend).__module__
            if not module.startswith(
                (
                    "keyring.backends.Windows",
                    "keyring.backends.macOS",
                    "keyring.backends.SecretService",
                )
            ):
                raise RuntimeError("No hay un almacén seguro del sistema. Caché deshabilitada.")
            key = keyring.get_password("PPS Desktop cache", self.scope)
            if not key:
                key = Fernet.generate_key().decode()
                keyring.set_password("PPS Desktop cache", self.scope, key)
        self.cipher = Fernet(key.encode() if isinstance(key, str) else key)

    def save(self, data):
        payload = json.dumps({"saved_at": self.clock(), "data": data}, ensure_ascii=False).encode()
        temporary = self.path.with_suffix(".tmp")
        temporary.write_bytes(self.cipher.encrypt(payload))
        temporary.replace(self.path)

    def load(self):
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.cipher.decrypt(self.path.read_bytes()))
            if not 0 <= self.clock() - payload["saved_at"] <= self.ttl:
                self.clear()
                return None
            return payload["data"]
        except (InvalidToken, ValueError, KeyError, TypeError):
            self.clear()
            return None

    def clear(self):
        self.path.unlink(missing_ok=True)

    @staticmethod
    def clear_all(root):
        for path in Path(root).glob("*.enc"):
            path.unlink()
