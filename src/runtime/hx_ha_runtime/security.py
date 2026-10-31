from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any


SENSITIVE_WORDS = ("password", "passwd", "token", "secret", "api_key", "apikey", "credential")


def split_secrets(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    public, secrets = {}, {}
    for key, value in data.items():
        (secrets if any(word in key.lower() for word in SENSITIVE_WORDS) else public)[key] = value
    return public, secrets


class CredentialVault:
    """Authenticated encrypted-at-rest storage using only the CPython standard library.

    The worker master key must be provisioned by HOMEX. A per-record random nonce and
    HMAC-derived stream keep plaintext credentials out of config-entry persistence.
    """

    def __init__(self, root: Path, master_key: bytes) -> None:
        if len(master_key) < 32:
            raise ValueError("master key must contain at least 32 bytes")
        self.root = root
        self.key = hashlib.sha256(master_key).digest()
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, namespace: str, entry_id: str) -> Path:
        safe = hashlib.sha256(f"{namespace}:{entry_id}".encode()).hexdigest()
        return self.root / f"{safe}.secret"

    def _stream(self, nonce: bytes, size: int) -> bytes:
        result, counter = bytearray(), 0
        while len(result) < size:
            result.extend(hmac.new(self.key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest())
            counter += 1
        return bytes(result[:size])

    def put(self, namespace: str, entry_id: str, values: dict[str, Any]) -> None:
        raw = json.dumps(values, separators=(",", ":"), sort_keys=True).encode()
        nonce = os.urandom(24)
        ciphertext = bytes(a ^ b for a, b in zip(raw, self._stream(nonce, len(raw))))
        tag = hmac.new(self.key, namespace.encode() + nonce + ciphertext, hashlib.sha256).digest()
        payload = base64.urlsafe_b64encode(nonce + tag + ciphertext)
        path = self._path(namespace, entry_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(payload)
        os.chmod(tmp, 0o600)
        tmp.replace(path)

    def get(self, namespace: str, entry_id: str) -> dict[str, Any]:
        path = self._path(namespace, entry_id)
        if not path.exists():
            return {}
        packed = base64.urlsafe_b64decode(path.read_bytes())
        nonce, tag, ciphertext = packed[:24], packed[24:56], packed[56:]
        expected = hmac.new(self.key, namespace.encode() + nonce + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise ValueError("credential authentication failed")
        raw = bytes(a ^ b for a, b in zip(ciphertext, self._stream(nonce, len(ciphertext))))
        return json.loads(raw)

    def delete(self, namespace: str, entry_id: str) -> None:
        self._path(namespace, entry_id).unlink(missing_ok=True)
