"""Fernet-encrypted local storage for provider API keys.

Master key lives in ~/.bindery/master.key (outside the repo); the encrypted
store lives in storage/.keys/keys.enc (gitignored). Keys are only ever sent
to their own provider's API, never logged, and only returned masked.
"""
import json
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

PROVIDERS = ("anthropic", "openai", "google")
MASTER = Path.home() / ".bindery" / "master.key"
STORE = Path(__file__).resolve().parent.parent / "storage" / ".keys" / "keys.enc"


def _fernet() -> Fernet:
    if not MASTER.exists():
        MASTER.parent.mkdir(parents=True, exist_ok=True)
        MASTER.write_bytes(Fernet.generate_key())
    return Fernet(MASTER.read_bytes())


def _load() -> dict:
    if not STORE.exists():
        return {}
    try:
        return json.loads(_fernet().decrypt(STORE.read_bytes()))
    except (InvalidToken, ValueError):
        return {}  # master key rotated or store corrupted; start fresh


def _save(keys: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_bytes(_fernet().encrypt(json.dumps(keys).encode()))


def set_key(provider: str, key: str) -> None:
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider}")
    keys = _load()
    keys[provider] = key.strip()
    _save(keys)


def delete_key(provider: str) -> None:
    keys = _load()
    keys.pop(provider, None)
    _save(keys)


def get_key(provider: str) -> str | None:
    return _load().get(provider) or None


def set_config(name: str, cfg: dict) -> None:
    """Store a small settings dict (e.g. Send-to-Kindle SMTP details) in the same
    encrypted store, under a 'cfg:' prefix so it never collides with providers."""
    keys = _load()
    keys[f"cfg:{name}"] = cfg
    _save(keys)


def get_config(name: str) -> dict:
    v = _load().get(f"cfg:{name}")
    return v if isinstance(v, dict) else {}


def masked() -> dict:
    keys = _load()
    return {p: (f"…{keys[p][-4:]}" if keys.get(p) else None) for p in PROVIDERS}
