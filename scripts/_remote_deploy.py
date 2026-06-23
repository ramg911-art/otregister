import paramiko
import sys

HOST = "192.168.10.216"
USER = "deploy"
PASSWORD = "cursor123"
APP_ROOT = "/home/ram/otregister"
SERVICE = "otregister"


def _print(s):
    sys.stdout.buffer.write(s.encode("utf-8", errors="replace"))
    if not s.endswith("\n"):
        sys.stdout.buffer.write(b"\n")


def run(client, cmd, timeout=300):
    _print(f"\n$ {cmd.strip()[:200]}...")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()
    code = stdout.channel.recv_exit_status()
    if out.strip():
        _print(out.rstrip("\n"))
    if err.strip():
        _print(err.rstrip("\n"))
    _print(f"[exit {code}]")
    return code, out, err


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        HOST,
        username=USER,
        password=PASSWORD,
        timeout=15,
        allow_agent=False,
        look_for_keys=False,
    )

    run(client, "whoami; hostname")

    deploy_cmds = f"""
set -e
git config --global --add safe.directory {APP_ROOT}
cd {APP_ROOT}
git fetch origin main
git reset --hard origin/main
if [ -d venv ]; then . venv/bin/activate; elif [ -d .venv ]; then . .venv/bin/activate; fi
pip install -r requirements.txt -q
mkdir -p uploads/iol_orders data
python -c 'from app.database import engine, ensure_iol_order_schema; ensure_iol_order_schema(engine); print(\"migrations ok\")'
sudo -n systemctl restart {SERVICE}
sleep 2
systemctl is-active {SERVICE}
curl -s -o /dev/null -w 'http_login=%{{http_code}}' http://127.0.0.1:8000/login || true
echo
git log -1 --oneline
"""
    code, out, err = run(client, deploy_cmds)
    client.close()
    if code != 0:
        sys.exit(code)
    _print("\nDeploy complete.")


if __name__ == "__main__":
    main()
