"""Autenticação + papéis (admin / vendedor).

Senhas com pbkdf2-hmac (stdlib), sessões opacas em banco. O vendedor é
ligado ao seu Id de usuário no Ploomes (owner_id) para ver só a própria
carteira; o admin vê tudo.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import hmac
import os
import secrets
from typing import Optional

import db

SESSION_DAYS = 30
ADMIN_EMAIL = os.getenv("CORTEX_ADMIN_EMAIL", "gabriel.hernandes@larplasticos.com.br")
DEFAULT_ADMIN_PWD = os.getenv("CORTEX_ADMIN_PWD", "cortex@admin")


# -- hashing -----------------------------------------------------------------
def hash_pwd(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return f"pbkdf2${salt.hex()}${h.hex()}"


def verify_pwd(password: str, stored: str) -> bool:
    try:
        _, salt_hex, hash_hex = stored.split("$")
        h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 120_000)
        return hmac.compare_digest(h.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


# -- usuários ----------------------------------------------------------------
def _now() -> str:
    return dt.datetime.now().isoformat()


def create_user(email: str, name: str, password: str, role: str = "seller",
                owner_id: Optional[int] = None) -> int:
    return db.run(
        "INSERT INTO users(email,name,role,owner_id,pwd,created) VALUES(?,?,?,?,?,?)",
        (email.lower().strip(), name, role, owner_id, hash_pwd(password), _now()),
    )


def user_by_email(email: str):
    return db.q1("SELECT * FROM users WHERE email=?", (email.lower().strip(),))


def list_users() -> list[dict]:
    return [dict(r) for r in db.q(
        "SELECT id,email,name,role,owner_id,COALESCE(active,1) active "
        "FROM users ORDER BY role,name")]


def set_password(user_id: int, password: str) -> None:
    db.run("UPDATE users SET pwd=? WHERE id=?", (hash_pwd(password), user_id))


def set_active(user_id: int, active: bool) -> None:
    db.run("UPDATE users SET active=? WHERE id=?", (1 if active else 0, user_id))
    if not active:
        db.run("DELETE FROM sessions WHERE user_id=?", (user_id,))


def ensure_admin() -> Optional[str]:
    """Cria o admin inicial se não houver nenhum usuário. Devolve a senha
    padrão na primeira vez (para você anotar e trocar)."""
    if db.q1("SELECT 1 FROM users LIMIT 1"):
        return None
    create_user(ADMIN_EMAIL, "Administrador", DEFAULT_ADMIN_PWD, role="admin")
    return DEFAULT_ADMIN_PWD


# -- sessões -----------------------------------------------------------------
def login(email: str, password: str) -> Optional[str]:
    u = user_by_email(email)
    if not u or not verify_pwd(password, u["pwd"]):
        return None
    try:
        if u["active"] == 0:
            return None
    except (KeyError, IndexError):
        pass
    token = secrets.token_urlsafe(32)
    expires = (dt.datetime.now() + dt.timedelta(days=SESSION_DAYS)).isoformat()
    db.run("INSERT INTO sessions(token,user_id,expires) VALUES(?,?,?)", (token, u["id"], expires))
    return token


def user_for_token(token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    row = db.q1(
        "SELECT u.id,u.email,u.name,u.role,u.owner_id,s.expires "
        "FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?",
        (token,),
    )
    if not row:
        return None
    if row["expires"] < _now():
        db.run("DELETE FROM sessions WHERE token=?", (token,))
        return None
    return {"id": row["id"], "email": row["email"], "name": row["name"],
            "role": row["role"], "owner_id": row["owner_id"]}


def logout(token: Optional[str]) -> None:
    if token:
        db.run("DELETE FROM sessions WHERE token=?", (token,))
