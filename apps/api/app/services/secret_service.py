"""Encrypted credential storage. The only module that sees plaintext API keys.

Plaintext exists only: in the request body when a key is submitted, inside ``store``
while encrypting, and inside ``reveal`` for the duration of one provider call. It is never
returned by an API, logged, or cached.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import EncryptedSecret, Keyring, secret_aad
from app.models import Secret
from app.models.enums import SecretKind


def last4(value: str) -> str:
    return value[-4:] if len(value) >= 8 else ""


def mask(last_four: str | None) -> str | None:
    """Display form of a stored key: '••••abcd' (or '••••' for very short keys)."""
    if last_four is None:
        return None
    return f"••••{last_four}"


def store(
    db: Session,
    keyring: Keyring,
    owner_id: uuid.UUID,
    plaintext: str,
    kind: SecretKind = SecretKind.LLM_API_KEY,
) -> Secret:
    """Encrypt and add a new secret to the session (caller commits)."""
    secret_id = uuid.uuid4()
    enc = keyring.encrypt(plaintext, secret_aad(secret_id, owner_id))
    secret = Secret(
        id=secret_id,
        owner_id=owner_id,
        kind=kind.value,
        ciphertext=enc.ciphertext,
        nonce=enc.nonce,
        wrapped_dek=enc.wrapped_dek,
        dek_nonce=enc.dek_nonce,
        kek_id=enc.kek_id,
        last4=last4(plaintext),
    )
    db.add(secret)
    return secret


def _encrypted(secret: Secret) -> EncryptedSecret:
    return EncryptedSecret(
        ciphertext=secret.ciphertext,
        nonce=secret.nonce,
        wrapped_dek=secret.wrapped_dek,
        dek_nonce=secret.dek_nonce,
        kek_id=secret.kek_id,
    )


def reveal(keyring: Keyring, secret: Secret, owner_id: uuid.UUID) -> str:
    """Decrypt for immediate use. ``owner_id`` must be the caller's user: the AAD check
    makes a secret belonging to someone else fail to decrypt even if it were loaded."""
    return keyring.decrypt(_encrypted(secret), secret_aad(secret.id, owner_id))


def get_owned(db: Session, owner_id: uuid.UUID, secret_id: uuid.UUID) -> Secret | None:
    return db.scalar(select(Secret).where(Secret.id == secret_id, Secret.owner_id == owner_id))


def rewrap_all(db: Session, keyring: Keyring, batch_size: int = 200) -> int:
    """Re-wrap every secret's data key under the active KEK. Returns the number changed.

    Used after rotating SECRETS_MASTER_KEY: put the old key in SECRETS_PREVIOUS_KEYS, run
    this, then remove the old key. Ciphertexts are unchanged; only wrapped DEKs change.
    """
    changed = 0
    while True:
        rows = list(
            db.scalars(
                select(Secret)
                .where(Secret.kek_id != keyring.active_id)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        )
        if not rows:
            break
        for secret in rows:
            new = keyring.rewrap(_encrypted(secret), secret_aad(secret.id, secret.owner_id))
            secret.wrapped_dek = new.wrapped_dek
            secret.dek_nonce = new.dek_nonce
            secret.kek_id = new.kek_id
            secret.rotated_at = datetime.now(UTC)
            changed += 1
        db.commit()
    return changed
