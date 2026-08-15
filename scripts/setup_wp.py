"""
워드프레스(hyunjiunni.com) 초기 설정 래퍼 — setup_wp_remote.sh 실행 + mu-plugin 동기화.

사용법:
  py scripts/setup_wp.py
  py scripts/setup_wp.py --check-only
"""
from __future__ import annotations

import argparse
import base64
import subprocess
import sys
from pathlib import Path

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

ROOT = Path(__file__).resolve().parents[1]
# repo 밖 공통 위치 우선, 없으면 레거시 경로
_DEFAULT_KEYS = (
    ROOT.parents[1] / "hyunji-key.pem",  # C:\...\CLAUDE\hyunji-key.pem
    ROOT.parent / "2026.07.07 23.05_ssh" / "hyunji-key.pem",
)
DEFAULT_KEY = next((p for p in _DEFAULT_KEYS if p.exists()), _DEFAULT_KEYS[0])
DEFAULT_HOST = "ubuntu@13.209.190.8"
REMOTE_SH = Path(__file__).with_name("setup_wp_remote.sh")


def _ssh(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", check=check)


def ssh_run(remote_cmd: str) -> str:
    key = Path(__import__("os").environ.get("WP_SSH_KEY", DEFAULT_KEY))
    host = __import__("os").environ.get("WP_SSH_HOST", DEFAULT_HOST)
    r = _ssh(["ssh", "-i", str(key), "-o", "StrictHostKeyChecking=no", host, remote_cmd])
    if r.returncode != 0:
        raise RuntimeError(r.stderr or r.stdout)
    return r.stdout


def scp(local: Path, remote: str) -> None:
    key = Path(__import__("os").environ.get("WP_SSH_KEY", DEFAULT_KEY))
    host = __import__("os").environ.get("WP_SSH_HOST", DEFAULT_HOST)
    _ssh(["scp", "-i", str(key), "-o", "StrictHostKeyChecking=no", str(local), f"{host}:{remote}"])


def sync_mu_plugins() -> None:
    assets = ROOT / "poster" / "wp_assets"
    names = ("hyunji-style.css", "hyunji-style.php", "hyunji-seo.php", "hyunji-favicon.png")
    for name in names:
        local = assets / name
        if not local.exists():
            if name == "hyunji-favicon.png":
                subprocess.run([sys.executable, str(assets / "gen_favicon.py")], check=True, cwd=str(ROOT))
            else:
                raise FileNotFoundError(local)
        scp(local, f"/tmp/{name}")
    ssh_run(
        "sudo cp /tmp/hyunji-style.css /tmp/hyunji-style.php /tmp/hyunji-seo.php "
        "/tmp/hyunji-favicon.png /var/www/html/wp-content/mu-plugins/ "
        "&& sudo chown www-data:www-data /var/www/html/wp-content/mu-plugins/hyunji-*"
    )


def run_setup() -> None:
    scp(REMOTE_SH, "/tmp/setup_wp_remote.sh")
    ssh_run(
        "tr -d '\\r' < /tmp/setup_wp_remote.sh > /tmp/setup_wp_fixed.sh "
        "&& chmod +x /tmp/setup_wp_fixed.sh && bash /tmp/setup_wp_fixed.sh"
    )


def check() -> None:
    print(ssh_run(
        "sudo -u www-data wp --path=/var/www/html term list category --fields=term_id,name,slug,count; "
        "echo ---; sudo -u www-data wp --path=/var/www/html option get blogname; "
        "sudo -u www-data wp --path=/var/www/html theme list --status=active --field=name"
    ))


def check_rest() -> None:
    sys.path.insert(0, str(ROOT))
    try:
        import requests
        from config import WP_URL, WP_USER, WP_APP_PW
    except Exception as e:
        print(f"REST skip: {e}")
        return
    if not (WP_URL and WP_USER and WP_APP_PW):
        print("REST: .env WP_* 미설정")
        return
    auth = base64.b64encode(f"{WP_USER}:{WP_APP_PW}".encode()).decode()
    r = requests.get(f"{WP_URL.rstrip('/')}/wp-json/wp/v2/users/me",
                     headers={"Authorization": f"Basic {auth}"}, timeout=30)
    print(f"REST: {r.status_code} {r.json().get('name') if r.ok else r.text[:100]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()
    if args.check_only:
        check()
        check_rest()
        return
    print("mu-plugin 동기화...")
    sync_mu_plugins()
    print("원격 WP 설정 실행...")
    run_setup()
    check()


if __name__ == "__main__":
    main()
