"""Field and file encryption (AES-256-GCM) with per-lead data keys wrapped by a master key."""
import hashlib
import hmac
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import config


def _kek(version):
    key = config.MASTER_KEYS.get(version)
    if key is None:
        raise RuntimeError(f"MASTER_KEY_V{version} is needed to read this data but is not configured.")
    return AESGCM(key)


def encrypt(key, data: bytes, aad: bytes = b"") -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, data, aad)


def decrypt(key, blob, aad: bytes = b"") -> bytes:
    blob = bytes(blob)
    return AESGCM(key).decrypt(blob[:12], blob[12:], aad)


def enc_text(key, value):
    return encrypt(key, value.encode()) if value else None


def dec_text(key, blob):
    return decrypt(key, blob).decode() if blob is not None else None


def enc_json(key, obj):
    return encrypt(key, json.dumps(obj, ensure_ascii=False).encode())


def dec_json(key, blob):
    return json.loads(decrypt(key, blob)) if blob is not None else {}


def blind_index(value: str) -> bytes:
    """Lets us look a value up (e.g. a mobile number) without storing it in plain text."""
    return hmac.new(config.INDEX_KEY, value.strip().lower().encode(), hashlib.sha256).digest()


def create_data_key(cur, org_id, owner_type, owner_id):
    raw = os.urandom(32)
    nonce = os.urandom(12)
    wrapped = nonce + _kek(config.KEK_VERSION).encrypt(nonce, raw, b"data-key")
    cur.execute(
        """INSERT INTO data_keys (org_id, owner_type, owner_id, wrapped, kek_version)
           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
        (org_id, owner_type, owner_id, wrapped, config.KEK_VERSION),
    )
    return cur.fetchone()["id"], raw


class KeyRing:
    """Unwraps data keys on demand and remembers them for the rest of the request."""

    def __init__(self, cur):
        self.cur = cur
        self.keys = {}

    def get(self, key_id):
        key_id = str(key_id)
        if key_id not in self.keys:
            self.cur.execute("SELECT wrapped, kek_version FROM data_keys WHERE id = %s", (key_id,))
            row = self.cur.fetchone()
            if not row or row["wrapped"] is None:
                raise LookupError("This data has been erased.")
            self.keys[key_id] = self.unwrap(row["wrapped"], row["kek_version"])
        return self.keys[key_id]

    @staticmethod
    def unwrap(wrapped, version):
        wrapped = bytes(wrapped)
        return _kek(version).decrypt(wrapped[:12], wrapped[12:], b"data-key")
