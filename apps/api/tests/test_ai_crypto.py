"""Credential encryption: AES-256-GCM envelope, AAD binding, tamper detection, rotation."""

import uuid

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.crypto import (
    DecryptionError,
    EncryptedSecret,
    EncryptionNotConfiguredError,
    Keyring,
    decode_key,
    encryption_configured,
    generate_master_key,
    keyring_from_settings,
    secret_aad,
)

PLAINTEXT = "sk-test-0123456789abcdefABCDEF-very-secret"


def _keyring(kid: str = "k1") -> Keyring:
    return Keyring(kid, {kid: decode_key(generate_master_key())})


def _aad() -> bytes:
    return secret_aad(uuid.uuid4(), uuid.uuid4())


def test_round_trip_and_ciphertext_hides_plaintext() -> None:
    kr = _keyring()
    aad = _aad()
    enc = kr.encrypt(PLAINTEXT, aad)
    assert PLAINTEXT.encode() not in enc.ciphertext
    assert PLAINTEXT.encode() not in enc.wrapped_dek
    assert len(enc.nonce) == 12 and len(enc.dek_nonce) == 12
    assert kr.decrypt(enc, aad) == PLAINTEXT


def test_each_encryption_uses_fresh_nonce_and_dek() -> None:
    kr = _keyring()
    aad = _aad()
    a, b = kr.encrypt(PLAINTEXT, aad), kr.encrypt(PLAINTEXT, aad)
    assert a.ciphertext != b.ciphertext
    assert a.nonce != b.nonce
    assert a.wrapped_dek != b.wrapped_dek


def test_aad_binds_ciphertext_to_secret_and_owner() -> None:
    kr = _keyring()
    secret_id, owner = uuid.uuid4(), uuid.uuid4()
    enc = kr.encrypt(PLAINTEXT, secret_aad(secret_id, owner))
    with pytest.raises(DecryptionError):
        kr.decrypt(enc, secret_aad(secret_id, uuid.uuid4()))  # another user's row
    with pytest.raises(DecryptionError):
        kr.decrypt(enc, secret_aad(uuid.uuid4(), owner))  # copied onto another secret


@pytest.mark.parametrize("field", ["ciphertext", "nonce", "wrapped_dek", "dek_nonce"])
def test_tampering_is_detected(field: str) -> None:
    kr = _keyring()
    aad = _aad()
    enc = kr.encrypt(PLAINTEXT, aad)
    raw = bytearray(getattr(enc, field))
    raw[0] ^= 0x01
    tampered = EncryptedSecret(**{**enc.__dict__, field: bytes(raw)})
    with pytest.raises(DecryptionError):
        kr.decrypt(tampered, aad)


def test_wrong_master_key_fails() -> None:
    aad = _aad()
    enc = _keyring().encrypt(PLAINTEXT, aad)
    with pytest.raises(DecryptionError):
        _keyring().decrypt(enc, aad)


def test_unknown_key_id_explains_what_to_do() -> None:
    aad = _aad()
    enc = _keyring("old").encrypt(PLAINTEXT, aad)
    with pytest.raises(DecryptionError, match="SECRETS_PREVIOUS_KEYS"):
        _keyring("new").decrypt(enc, aad)


def test_rotation_rewraps_dek_without_touching_ciphertext() -> None:
    old_key, new_key = decode_key(generate_master_key()), decode_key(generate_master_key())
    aad = _aad()
    enc = Keyring("k1", {"k1": old_key}).encrypt(PLAINTEXT, aad)

    rotating = Keyring("k2", {"k2": new_key, "k1": old_key})
    assert rotating.decrypt(enc, aad) == PLAINTEXT  # old secrets still readable
    rewrapped = rotating.rewrap(enc, aad)
    assert rewrapped.kek_id == "k2"
    assert rewrapped.ciphertext == enc.ciphertext
    assert rewrapped.wrapped_dek != enc.wrapped_dek

    only_new = Keyring("k2", {"k2": new_key})  # old key removed after rotation
    assert only_new.decrypt(rewrapped, aad) == PLAINTEXT
    with pytest.raises(DecryptionError):
        only_new.decrypt(enc, aad)


@pytest.mark.parametrize("bad", ["", "not base64 !!", "c2hvcnQ"])
def test_invalid_master_keys_are_rejected(bad: str) -> None:
    with pytest.raises(EncryptionNotConfiguredError):
        decode_key(bad)


def test_keyring_from_settings_with_previous_keys() -> None:
    active, previous = generate_master_key(), generate_master_key()
    settings = Settings(
        jwt_secret="j" * 40,
        secrets_master_key=SecretStr(active),
        secrets_master_key_id="k2",
        secrets_previous_keys=SecretStr(f"k1:{previous}"),
    )
    kr = keyring_from_settings(settings)
    assert kr.active_id == "k2"
    assert sorted(kr.key_ids) == ["k1", "k2"]


def test_missing_master_key_means_not_configured() -> None:
    settings = Settings(jwt_secret="j" * 40, secrets_master_key=None)
    assert encryption_configured(settings) is False
    with pytest.raises(EncryptionNotConfiguredError, match="SECRETS_MASTER_KEY"):
        keyring_from_settings(settings)


def test_settings_repr_does_not_leak_master_key() -> None:
    key = generate_master_key()
    settings = Settings(jwt_secret="j" * 40, secrets_master_key=SecretStr(key))
    assert key not in repr(settings)
    assert key not in str(settings.model_dump())
