"""Encrypted provider credentials for the hosted profile."""
import os

from cryptography.fernet import Fernet, InvalidToken

from . import db
from .errors import AppError


def validate_key() -> None:
    if os.environ.get("JIANZHOU_SECRET_KEY"):
        _cipher()


def _cipher() -> Fernet:
    key = os.environ.get("JIANZHOU_SECRET_KEY", "")
    if not key:
        raise AppError("SECRET_STORE_UNAVAILABLE", "请先在云端配置凭据加密密钥。", http_status=503)
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise AppError("SECRET_KEY_INVALID", "云端凭据加密密钥格式无效。", http_status=503) from exc


def get(name: str) -> str:
    row = db.query_one("SELECT ciphertext FROM web_secrets WHERE name=?", (name,))
    if not row:
        return ""
    try:
        return _cipher().decrypt(row["ciphertext"]).decode()
    except InvalidToken as exc:
        raise AppError("SECRET_DECRYPT_FAILED", "无法解密凭据。请检查云端加密密钥。", http_status=503) from exc


def set_value(name: str, value: str) -> None:
    if value:
        db.execute("INSERT OR REPLACE INTO web_secrets(name,ciphertext) VALUES(?,?)", (name, _cipher().encrypt(value.encode())))
    else:
        db.execute("DELETE FROM web_secrets WHERE name=?", (name,))
