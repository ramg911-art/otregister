import paramiko
import sys
from pathlib import Path

HOST = "192.168.10.216"
USER = "deploy"
PASSWORD = "cursor123"
APP_ROOT = "/home/ram/otregister"
LOCAL_SCRIPT = Path(__file__).resolve().parent / "_remote_check_schema.py"
REMOTE_SCRIPT = f"{APP_ROOT}/scripts/_remote_check_schema.py"


def p(s):
    sys.stdout.buffer.write(s.encode("utf-8", errors="replace"))
    if not s.endswith("\n"):
        sys.stdout.buffer.write(b"\n")


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        HOST, username=USER, password=PASSWORD, timeout=15,
        allow_agent=False, look_for_keys=False,
    )

    sftp = client.open_sftp()
    try:
        sftp.stat(f"{APP_ROOT}/scripts")
    except FileNotFoundError:
        client.exec_command(f"mkdir -p {APP_ROOT}/scripts")[1].channel.recv_exit_status()
    sftp.put(str(LOCAL_SCRIPT), REMOTE_SCRIPT)
    sftp.close()

    cmd = f"cd {APP_ROOT} && . venv/bin/activate && python scripts/_remote_check_schema.py"
    stdin, stdout, stderr = client.exec_command(cmd, timeout=90)
    out = stdout.read().decode()
    err = stderr.read().decode()
    code = stdout.channel.recv_exit_status()
    p(out)
    if err.strip():
        p("STDERR:\n" + err)
    p(f"exit {code}")
    client.close()
    sys.exit(code)


if __name__ == "__main__":
    main()
