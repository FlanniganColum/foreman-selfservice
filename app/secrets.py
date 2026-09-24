"""Write-only Vault KV v2 integration for submitted Chiklet secrets.

The portal never reads a secret back. Foreman receives references only and must
resolve them using a separate, narrowly scoped read credential at execution.
"""
import re
from pathlib import Path
from urllib.parse import quote

import requests
from flask import current_app


class SecretStoreError(RuntimeError):
    pass


def store_secrets(request_id, values):
    """Store all secret fields in one KV v2 version and return field references."""
    if not values:
        return {}
    cfg = current_app.config
    address = cfg["VAULT_ADDR"]
    token = cfg["VAULT_TOKEN"]
    if cfg["VAULT_TOKEN_FILE"]:
        try:
            token = Path(cfg["VAULT_TOKEN_FILE"]).read_text(encoding="utf-8").strip()
        except OSError:
            raise SecretStoreError("Secure secret storage is not configured") from None
    mount = cfg["VAULT_KV_MOUNT"].strip("/")
    prefix = cfg["VAULT_KV_PREFIX"].strip("/")
    if not address.startswith("https://") or not token or not mount or not prefix:
        raise SecretStoreError("Secure secret storage is not configured")
    if not all(re.fullmatch(r"[a-zA-Z0-9_-]+", part) for part in (mount, *prefix.split("/"))):
        raise SecretStoreError("Secure secret storage path is invalid")
    path = f"{prefix}/{request_id}"
    endpoint = f"{address.rstrip('/')}/v1/{quote(mount)}/data/{'/'.join(quote(p) for p in path.split('/'))}"
    try:
        response = requests.post(
            endpoint,
            headers={"X-Vault-Token": token, "Content-Type": "application/json"},
            json={"data": values},
            timeout=cfg["VAULT_TIMEOUT_SECONDS"],
            verify=cfg["VAULT_CA_BUNDLE"] or True,
        )
        response.raise_for_status()
    except requests.RequestException:
        # Never include response bodies, headers, request objects or URLs in errors.
        raise SecretStoreError("Could not store the sensitive fields securely") from None
    return {name: f"vault-kv2://{mount}/{path}#{name}" for name in values}
