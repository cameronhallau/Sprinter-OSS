from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_repository_contains_no_private_lab_markers() -> None:
    blocked = (
        "redhornet",
        "10.50.",
        "100.87.",
        "conflab99",
        "proxmox",
        "tailscale",
        "cloudflared",
    )
    text = "\n".join(
        path.read_text(errors="ignore").lower()
        for path in ROOT.rglob("*")
        if path.is_file()
        and ".venv" not in path.parts
        and "node_modules" not in path.parts
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
        and path.name != ".coverage"
        and path.name != "test_release_shape.py"
    )
    assert not [marker for marker in blocked if marker in text]


def test_container_and_compose_are_hardened() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    assert "USER 10001:10001" in dockerfile
    assert "sha256:" in dockerfile
    assert "0.83.0" in dockerfile or "package-lock.json" in dockerfile
    assert "site-packages/pip-*.dist-info" in dockerfile
    for service in compose["services"].values():
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert any("/run/secrets/sprinter:ro" in volume for volume in service["volumes"])
    assert compose["services"]["api"]["ports"] == ["127.0.0.1:8080:8080"]


def test_actions_are_commit_pinned() -> None:
    for workflow in (ROOT / ".github/workflows").glob("*.yml"):
        content = workflow.read_text()
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("- uses:"):
                reference = stripped.split("@", 1)[1]
                assert len(reference) == 40
                int(reference, 16)


def test_pi_lock_has_expected_package_and_integrity() -> None:
    lock = json.loads((ROOT / "package-lock.json").read_text())
    pi = lock["packages"]["node_modules/@earendil-works/pi-coding-agent"]
    assert pi["version"] == "0.83.0"
    assert (
        pi["integrity"]
        == "sha512-uYhF+FsZxogoSX/AxBcUdiY+ZklubwaXyAoEGA2eQwsHcyEAhUYIKh/WLXe/a8+k8eTCmxb+ZN2Zo9mzQtzbWw=="
    )
