import paramiko
import sys

FILES = [
    (r"d:\otregister\app\templating.py", "/home/ram/otregister/app/templating.py"),
    (r"d:\otregister\app\main.py", "/home/ram/otregister/app/main.py"),
    (r"d:\otregister\app\iol_order_routes.py", "/home/ram/otregister/app/iol_order_routes.py"),
]

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(
    "192.168.10.216",
    username="deploy",
    password="cursor123",
    timeout=15,
    allow_agent=False,
    look_for_keys=False,
)
sftp = c.open_sftp()
for local, remote in FILES:
    sftp.put(local, remote)
    print("uploaded", remote)
sftp.close()

cmd = (
    "cd /home/ram/otregister && . venv/bin/activate && "
    "python -c 'from app.templating import templates; "
    "assert \"user_can\" in templates.env.globals' && "
    "sudo -n systemctl restart otregister && sleep 2 && systemctl is-active otregister"
)
stdin, stdout, stderr = c.exec_command(cmd, timeout=60)
out = stdout.read().decode()
err = stderr.read().decode()
code = stdout.channel.recv_exit_status()
print(out, err, "exit", code)
c.close()
sys.exit(code)
