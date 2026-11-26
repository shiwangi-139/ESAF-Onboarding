"""Encrypted file storage on the server's disk.

Files live under STORAGE_DIR as random names (e.g. 3f/3f9c…e1.bin) with no personal data in the path.
Each file is AES-256-GCM encrypted with its lead's data key; the storage key is bound in as associated
data, so a file can't be swapped for another one without detection.
"""
import hashlib
import os
import uuid

import config
import crypto


def _path(storage_key):
    if ".." in storage_key or storage_key.startswith("/"):
        raise ValueError("bad storage key")
    return os.path.join(config.STORAGE_DIR, storage_key)


def put(data: bytes, key: bytes):
    name = uuid.uuid4().hex
    storage_key = f"{name[:2]}/{name}.bin"
    path = _path(storage_key)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(crypto.encrypt(key, data, storage_key.encode()))
    os.replace(tmp, path)
    return storage_key, hashlib.sha256(data).hexdigest()


def get(storage_key: str, key: bytes) -> bytes:
    with open(_path(storage_key), "rb") as f:
        return crypto.decrypt(key, f.read(), storage_key.encode())


def delete(storage_key: str):
    try:
        os.remove(_path(storage_key))
    except FileNotFoundError:
        pass
