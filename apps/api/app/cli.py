"""Maintenance commands.

    python -m app.cli generate-master-key      # print a new SECRETS_MASTER_KEY value
    python -m app.cli rotate-master-key        # re-wrap all stored keys under the active key
    python -m app.cli check-secrets            # verify every stored key can be decrypted

Rotation procedure (see README "Credential encryption"):
  1. Move the current key to SECRETS_PREVIOUS_KEYS as "<old id>:<old key>".
  2. Set SECRETS_MASTER_KEY to a new key and SECRETS_MASTER_KEY_ID to a new id.
  3. Restart the API, then run ``rotate-master-key``.
  4. Run ``check-secrets``; when it reports 0 on old keys, remove SECRETS_PREVIOUS_KEYS.
"""

import sys
from collections import Counter

from sqlalchemy import select

from app.core.config import get_settings
from app.core.crypto import (
    DecryptionError,
    EncryptionNotConfiguredError,
    generate_master_key,
    get_keyring,
)
from app.core.db import get_session_factory
from app.models import Secret
from app.services import secret_service


def _rotate() -> int:
    keyring = get_keyring(get_settings())
    with get_session_factory()() as db:
        changed = secret_service.rewrap_all(db, keyring)
    print(f"Re-wrapped {changed} secret(s) under key '{keyring.active_id}'.")
    return 0


def _check() -> int:
    keyring = get_keyring(get_settings())
    failures = 0
    by_key: Counter[str] = Counter()
    with get_session_factory()() as db:
        for secret in db.scalars(select(Secret)):
            by_key[secret.kek_id] += 1
            try:
                secret_service.reveal(keyring, secret, secret.owner_id)
            except DecryptionError:
                failures += 1
    print("Secrets by key id: " + (", ".join(f"{k}={v}" for k, v in by_key.items()) or "none"))
    print(f"Undecryptable: {failures}")
    stale = sum(v for k, v in by_key.items() if k != keyring.active_id)
    print(f"Still on previous keys: {stale}")
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    command = argv[0] if argv else ""
    try:
        if command == "generate-master-key":
            print(generate_master_key())
            return 0
        if command == "rotate-master-key":
            return _rotate()
        if command == "check-secrets":
            return _check()
    except (EncryptionNotConfiguredError, DecryptionError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(__doc__)
    return 64


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
