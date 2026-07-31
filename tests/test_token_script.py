from __future__ import annotations

import importlib.util
from pathlib import Path

from sprinter.config import verify_token

SCRIPT = Path(__file__).parents[1] / "scripts" / "hash_token.py"
SPEC = importlib.util.spec_from_file_location("hash_token", SCRIPT)
assert SPEC and SPEC.loader
hash_token = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hash_token)


def test_hash_script_emits_compatible_scrypt_verifier(monkeypatch, capsys) -> None:
    token = "test-token-with-at-least-24-characters"  # noqa: S105 - inert unit-test credential
    monkeypatch.setattr(hash_token.getpass, "getpass", lambda _prompt: token)
    monkeypatch.setattr(hash_token.os, "urandom", lambda _length: b"\x03" * 16)

    assert hash_token.main() == 0
    verifier = capsys.readouterr().out.strip()
    assert verifier.startswith("scrypt_16384_8_1_")
    assert verify_token(token, verifier)
    assert not verify_token("different-token", verifier)
