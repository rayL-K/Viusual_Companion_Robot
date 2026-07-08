from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_cloudflare_tunnel_survives_control_service_restart() -> None:
    service = (PROJECT_ROOT / "tools/systemd/visual-companion-cloudflared.service").read_text(encoding="utf-8")

    assert "After=network-online.target\n" in service
    assert "Requires=visual-companion-control.service" not in service


def test_start_script_removes_obsolete_resident_voxcpm() -> None:
    script = (PROJECT_ROOT / "tools/board/start_all.sh").read_text(encoding="utf-8")

    assert "systemctl disable --now visual-companion-voxcpm.service" in script
    assert "pkill -x voxcpm-server" in script
    assert "visual-companion-voxcpm.service\n" not in script.split("readonly SERVICES=(", 1)[1].split(")", 1)[0]


def test_deployment_verifier_covers_local_public_and_vox_invariants() -> None:
    script = (PROJECT_ROOT / "tools/board/verify_deployment.sh").read_text(encoding="utf-8")

    for endpoint in ("/vision-health", "/asr-health", "voice=matcha_baker", "voice=voxcpm_board"):
        assert endpoint in script
    assert "https://robot.veyralux.org" in script
    assert "pgrep -x voxcpm-server" in script
    assert "sha256sum --check" in script


def test_windows_sync_targets_current_board_and_protects_runtime_data() -> None:
    script = (PROJECT_ROOT / "tools/sync_firefly.ps1").read_text(encoding="utf-8")

    assert 'RemoteHost = "elf2-desktop.local"' in script
    assert 'RemoteUser = "wenkang"' in script
    assert 'RemoteRoot = "/home/wenkang/embedded_competition"' in script
    assert '"archive", "--format=tar.gz"' in script
    for protected_path in (".venv/", "main/models/", "main/data/", "main/config/board.env"):
        assert f"--exclude='{protected_path}'" in script
