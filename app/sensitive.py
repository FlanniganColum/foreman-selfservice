"""Protect sensitive Chiklet inputs while requests wait for execution.

The worker decrypts them only when it builds a Foreman job invocation. The
application SECRET_KEY must remain stable until outstanding jobs finish.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


PREFIX = "enc-v1:"


class SensitiveDataError(RuntimeError):
    pass


def _cipher(secret_key):
    if (not isinstance(secret_key, str) or len(secret_key) < 32 or
            secret_key in {"CHANGE-ME", "replace-with-at-least-64-random-characters"}):
        raise SensitiveDataError("A strong, stable SECRET_KEY is required for sensitive fields")
    material = hashlib.sha256(b"foreman-selfservice:sensitive-v1:" + secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def protect_fields(values, names, secret_key):
    names = set(names) & values.keys()
    if not names:
        return dict(values)
    cipher = _cipher(secret_key)
    protected = dict(values)
    for name in names:
        protected[name] = PREFIX + cipher.encrypt(values[name].encode()).decode("ascii")
    return protected


def reveal_fields(values, names, secret_key):
    names = set(names) & values.keys()
    if not names:
        return dict(values)
    cipher = _cipher(secret_key)
    revealed = dict(values)
    for name in names:
        value = values[name]
        if not isinstance(value, str) or not value.startswith(PREFIX):
            # Old requests may still contain a Vault reference. Keep their
            # original job-template behavior during the migration.
            if isinstance(value, str) and value.startswith("vault-kv2://"):
                continue
            raise SensitiveDataError("Sensitive request value is unavailable")
        try:
            revealed[name] = cipher.decrypt(value[len(PREFIX):].encode("ascii")).decode()
        except (InvalidToken, ValueError, UnicodeError):
            raise SensitiveDataError("Sensitive request value cannot be decrypted") from None
    return revealed
