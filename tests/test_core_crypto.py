"""字段级加密（core.crypto）与凭证会话密钥落库形态."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from cndb.core.config import settings
from cndb.core.crypto import (
    ENC_PREFIX,
    SecretDecryptError,
    decrypt_secret,
    decrypt_secrets,
    encrypt_secret,
    encrypt_secrets,
    is_encrypted,
    rotate_secrets,
)


@pytest.fixture(autouse=True)
def _restore_key():
    """每个用例后还原密钥缓存，避免影响其它测试（lru_cache 会记住旧口令）."""
    from cndb.core import crypto

    old = settings.DATASOURCE_SECRET_KEY
    yield
    settings.DATASOURCE_SECRET_KEY = old
    crypto._fernet_for.cache_clear()


class TestRoundTrip:
    def test_encrypt_then_decrypt(self):
        token = encrypt_secret("sk-live-123")
        assert token.startswith(ENC_PREFIX)
        assert "sk-live-123" not in token
        assert decrypt_secret(token) == "sk-live-123"

    def test_ciphertext_is_not_deterministic(self):
        """Fernet 带随机 IV：同一明文两次加密结果不同，但都能解回原文."""
        first = encrypt_secret("same")
        second = encrypt_secret("same")
        assert first != second
        assert decrypt_secret(first) == decrypt_secret(second) == "same"

    def test_empty_value_passthrough(self):
        assert encrypt_secret("") == ""
        assert decrypt_secret("") == ""

    def test_already_encrypted_is_idempotent(self):
        token = encrypt_secret("abc")
        assert encrypt_secret(token) == token

    def test_mapping_keys_stay_plain(self):
        """键名（api_key / token）必须保留明文 —— 读接口要回显「已配置哪些密钥」."""
        encrypted = encrypt_secrets({"api_key": "v1", "token": "v2"})
        assert set(encrypted) == {"api_key", "token"}
        assert all(is_encrypted(value) for value in encrypted.values())
        assert decrypt_secrets(encrypted) == {"api_key": "v1", "token": "v2"}

    def test_decrypt_none_mapping(self):
        assert decrypt_secrets(None) == {}


class TestLegacyPlaintext:
    def test_plaintext_value_passes_through(self):
        """存量明文（无前缀）读时原样返回，避免升级即报错."""
        assert decrypt_secret("legacy-plain") == "legacy-plain"
        assert decrypt_secrets({"old": "plain"}) == {"old": "plain"}
        assert not is_encrypted("plain")

    def test_is_encrypted_ignores_non_string(self):
        assert not is_encrypted(None)
        assert not is_encrypted(123)


class TestKeyHandling:
    def test_wrong_key_raises(self):
        token = encrypt_secret("secret-value")
        settings.DATASOURCE_SECRET_KEY = "another-key"
        from cndb.core import crypto

        crypto._fernet_for.cache_clear()
        with pytest.raises(SecretDecryptError) as excinfo:
            decrypt_secret(token)
        assert "DATASOURCE_SECRET_KEY" in str(excinfo.value)

    def test_falls_back_to_jwt_secret(self, monkeypatch):
        settings.DATASOURCE_SECRET_KEY = ""
        monkeypatch.setattr(settings, "JWT_SECRET", "fallback-secret")
        from cndb.core import crypto

        crypto._fernet_for.cache_clear()
        assert decrypt_secret(encrypt_secret("x")) == "x"

    def test_corrupted_payload_raises(self):
        with pytest.raises(SecretDecryptError):
            decrypt_secret(f"{ENC_PREFIX}not-a-valid-token")

    def test_rotate_reencrypts_with_new_key(self):
        settings.DATASOURCE_SECRET_KEY = "old-key"
        from cndb.core import crypto

        crypto._fernet_for.cache_clear()
        old_cipher = encrypt_secrets({"api_key": "v"})

        rotated = rotate_secrets(old_cipher, new_secret="new-key")
        # rotate 只负责「用新口令重加密」，配置切换由运维在写回后自行完成
        assert settings.DATASOURCE_SECRET_KEY == "old-key"

        settings.DATASOURCE_SECRET_KEY = "new-key"
        crypto._fernet_for.cache_clear()
        assert decrypt_secrets(rotated) == {"api_key": "v"}

    def test_derived_key_is_valid_fernet_key(self):
        """派生结果必须是 32 字节 urlsafe-base64，否则 Fernet 构造就炸."""
        from cndb.core.crypto import _fernet_for

        assert isinstance(_fernet_for("any-secret"), Fernet)
