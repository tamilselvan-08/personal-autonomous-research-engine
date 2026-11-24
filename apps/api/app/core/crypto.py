"""Envelope encryption for stored credentials (AES-256-GCM).

Each secret gets its own random 256-bit data-encryption key (DEK). The plaintext is
encrypted with the DEK; the DEK is encrypted ("wrapped") with the key-encryption key
(KEK) from the environment. Both encryptions are AES-GCM, so any tampering with the
ciphertext, the wrapped DEK, or the bound context (AAD) makes decryption fail.

The AAD binds a ciphertext to its database row and owner: a ciphertext copied into
another user's row, or onto another secret's id, will not decrypt.

Key rotation only re-wraps DEKs with the new KEK (``rewrap``); secret ciphertexts are
untouched. The KEK never touches the database; only its short id (``kek_id``) is stored.
"""

import base64
import binascii
import os
import uuid
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Settings

KEY_BYTES = 32
NONCE_BYTES = 12


class EncryptionNotConfiguredError(RuntimeError):
    """SECRETS_MASTER_KEY is missing or invalid."""


class DecryptionError(RuntimeError):
    """Ciphertext could not be authenticated (wrong key, wrong context, or tampering)."""


def generate_master_key() -> str:
    """A new random KEK, base64url-encoded, suitable for SECRETS_MASTER_KEY."""
    return base64.urlsafe_b64encode(os.urandom(KEY_BYTES)).decode("ascii").rstrip("=")


def decode_key(value: str) -> bytes:
    """Accept standard or URL-safe base64, with or without padding."""
    raw = value.strip()
    padded = raw + "=" * (-len(raw) % 4)
    try:
        key = base64.urlsafe_b64decode(padded.replace("+", "-").replace("/", "_"))
    except (binascii.Error, ValueError) as exc:
        raise EncryptionNotConfiguredError("Encryption key is not valid base64.") from exc
    if len(key) != KEY_BYTES:
        raise EncryptionNotConfiguredError(
            f"Encryption key must decode to {KEY_BYTES} bytes (got {len(key)})."
        )
    return key


@dataclass(frozen=True)
class EncryptedSecret:
    ciphertext: bytes
    nonce: bytes
    wrapped_dek: bytes
    dek_nonce: bytes
    kek_id: str


def secret_aad(secret_id: uuid.UUID, owner_id: uuid.UUID) -> bytes:
    return b"pare-secret:v1:" + secret_id.bytes + owner_id.bytes


class Keyring:
    """The active KEK plus any previous KEKs kept for decryption during rotation."""

    def __init__(self, active_id: str, keys: dict[str, bytes]) -> None:
        if active_id not in keys:
            raise EncryptionNotConfiguredError("Active encryption key id has no key.")
        self.active_id = active_id
        self._keys = dict(keys)

    @property
    def key_ids(self) -> list[str]:
        return list(self._keys)

    def _kek(self, kek_id: str) -> bytes:
        try:
            return self._keys[kek_id]
        except KeyError as exc:
            raise DecryptionError(
                f"Encryption key '{kek_id}' is not configured. Add it to SECRETS_PREVIOUS_KEYS."
            ) from exc

    @staticmethod
    def _dek_aad(aad: bytes, kek_id: str) -> bytes:
        return aad + b":dek:" + kek_id.encode("ascii")

    def encrypt(self, plaintext: str, aad: bytes) -> EncryptedSecret:
        dek = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = AESGCM(dek).encrypt(nonce, plaintext.encode("utf-8"), aad)
        dek_nonce = os.urandom(NONCE_BYTES)
        wrapped = AESGCM(self._kek(self.active_id)).encrypt(
            dek_nonce, dek, self._dek_aad(aad, self.active_id)
        )
        return EncryptedSecret(ciphertext, nonce, wrapped, dek_nonce, self.active_id)

    def _unwrap(self, enc: EncryptedSecret, aad: bytes) -> bytes:
        try:
            return AESGCM(self._kek(enc.kek_id)).decrypt(
                enc.dek_nonce, enc.wrapped_dek, self._dek_aad(aad, enc.kek_id)
            )
        except InvalidTag as exc:
            raise DecryptionError("Stored credential could not be decrypted.") from exc

    def decrypt(self, enc: EncryptedSecret, aad: bytes) -> str:
        dek = self._unwrap(enc, aad)
        try:
            return AESGCM(dek).decrypt(enc.nonce, enc.ciphertext, aad).decode("utf-8")
        except InvalidTag as exc:
            raise DecryptionError("Stored credential could not be decrypted.") from exc

    def rewrap(self, enc: EncryptedSecret, aad: bytes) -> EncryptedSecret:
        """Re-encrypt the DEK under the active KEK. The ciphertext is unchanged."""
        if enc.kek_id == self.active_id:
            return enc
        dek = self._unwrap(enc, aad)
        dek_nonce = os.urandom(NONCE_BYTES)
        wrapped = AESGCM(self._kek(self.active_id)).encrypt(
            dek_nonce, dek, self._dek_aad(aad, self.active_id)
        )
        return EncryptedSecret(enc.ciphertext, enc.nonce, wrapped, dek_nonce, self.active_id)


def keyring_from_settings(settings: Settings) -> Keyring:
    if settings.secrets_master_key is None or not settings.secrets_master_key.get_secret_value():
        raise EncryptionNotConfiguredError(
            "SECRETS_MASTER_KEY is not set. Run scripts/setup-env or add a key to .env "
            "(see README: Credential encryption)."
        )
    active = settings.secrets_master_key.get_secret_value()
    if active.strip().startswith("CHANGE_ME"):
        raise EncryptionNotConfiguredError(
            "SECRETS_MASTER_KEY is still the placeholder value. Run scripts/setup-env."
        )
    keys = {settings.secrets_master_key_id: decode_key(active)}
    if settings.secrets_previous_keys is not None:
        for item in settings.secrets_previous_keys.get_secret_value().split(","):
            if not item.strip():
                continue
            kid, sep, value = item.strip().partition(":")
            if not sep or not kid:
                raise EncryptionNotConfiguredError(
                    "SECRETS_PREVIOUS_KEYS must look like 'k1:<base64>,k0:<base64>'."
                )
            keys.setdefault(kid.strip(), decode_key(value))
    return Keyring(settings.secrets_master_key_id, keys)


def get_keyring(settings: Settings) -> Keyring:
    """Build the keyring from settings (cheap: two base64 decodes). Raises if unconfigured."""
    return keyring_from_settings(settings)


def encryption_configured(settings: Settings) -> bool:
    try:
        keyring_from_settings(settings)
    except EncryptionNotConfiguredError:
        return False
    return True
