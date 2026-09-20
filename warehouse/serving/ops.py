"""Project-owned MySQL lifecycle. Never change unrelated containers or volumes."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from .common import ARTIFACTS, DATABASE, ROOT, RUNTIME

CONTAINER = "jpj-mysql-serving-20260918"
VOLUME = "jpj-mysql-serving-20260918-data"
IMAGE = "mysql:8.4.6@sha256:869218921e61d6c3c89820955d63cca42971f0e3e6c1e2792247bbd944ebc6e9"
PREFIX = ["wsl", "-d", "Ubuntu-24.04", "--exec"] if os.name == "nt" else []


def docker(*args, input=None, check=True):
    result = subprocess.run(PREFIX + ["docker", *args], input=input, text=True,
        encoding="utf-8", errors="replace", capture_output=True)
    if check and result.returncode:
        raise RuntimeError(f"docker {args[0]} failed: {result.stderr[-1800:]}")
    return result


def prepare_config():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    cfg_path = RUNTIME / "config.json"
    if cfg_path.exists():
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg = {"host": "127.0.0.1", "port": 13306,
           "reader": {"user": "jpj_reader", "password": secrets.token_hex(24)},
           "writer": {"user": "jpj_writer", "password": secrets.token_hex(24)}}
    root_password = secrets.token_hex(32)
    secret_dir = RUNTIME / "secrets"
    secret_dir.mkdir(exist_ok=True)
    (secret_dir / "root-password").write_text(root_password, encoding="utf-8")
    (secret_dir / "root.cnf").write_text("[client]\nuser=root\npassword=" + root_password + "\n", encoding="utf-8")
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


def root_sql(sql):
    return docker("exec", "-i", CONTAINER, "mysql", "--defaults-extra-file=/tmp/jpj-root.cnf", "--protocol=TCP", "-h127.0.0.1", "--batch", input=sql).stdout


def start():
    cfg = prepare_config()
    inspected = docker("inspect", CONTAINER, check=False)
    if inspected.returncode:
        docker("pull", IMAGE)
        mount_path = (RUNTIME / "secrets").resolve().as_posix()
        if os.name == "nt":
            mount_path = subprocess.check_output(PREFIX + ["wslpath", "-a", mount_path], text=True, encoding="utf-8").strip()
        docker("run", "-d", "--name", CONTAINER, "--label", "project=malaysia-auto-ask-jpj-serving",
               "--memory=1536m", "--cpus=2", "--restart=no",
               "-p", f"127.0.0.1:{cfg['port']}:3306", "-v", f"{VOLUME}:/var/lib/mysql",
               "-v", f"{mount_path}:/run/secrets:ro",
               "-e", "MYSQL_ROOT_PASSWORD_FILE=/run/secrets/root-password", IMAGE,
               "--innodb-buffer-pool-size=256M", "--max-connections=40", "--mysqlx=OFF")
    else:
        info = json.loads(inspected.stdout)[0]
        if info["Config"].get("Labels", {}).get("project") != "malaysia-auto-ask-jpj-serving":
            raise RuntimeError("Container name collision: not owned by this project")
        docker("start", CONTAINER)
    docker("exec", CONTAINER, "sh", "-c", "cp /run/secrets/root.cnf /tmp/jpj-root.cnf && chmod 600 /tmp/jpj-root.cnf")
    for _ in range(60):
        ready = docker("exec", CONTAINER, "mysql", "--defaults-extra-file=/tmp/jpj-root.cnf", "--protocol=TCP", "-h127.0.0.1", "--batch", "-e", "SELECT 1", check=False)
        if ready.returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("MySQL did not become ready; inspect project container logs")
    if os.name == "nt":
        # Keep this WSL session alive after the setup process ends. Stopping only
        # our container makes docker wait exit naturally; no global WSL setting.
        with (RUNTIME / "keepalive.log").open("ab") as log:
            keeper = subprocess.Popen(PREFIX + ["docker", "wait", CONTAINER],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW)
        (RUNTIME / "keepalive.pid").write_text(str(keeper.pid), encoding="ascii")
    root_sql((Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8"))
    # Passwords are generated hex strings and are sent on stdin, never command-line/log output.
    for role, grants in [("reader", "SELECT"), ("writer", "SELECT,INSERT,UPDATE,DELETE")]:
        user, password = cfg[role]["user"], cfg[role]["password"]
        root_sql(f"CREATE USER IF NOT EXISTS '{user}'@'%' IDENTIFIED BY '{password}';\n"
                 f"ALTER USER '{user}'@'%' IDENTIFIED BY '{password}';\n"
                 f"GRANT {grants} ON {DATABASE}.* TO '{user}'@'%';\n")
    info = json.loads(docker("inspect", CONTAINER).stdout)[0]
    evidence = {"checked_at_utc": datetime.now(timezone.utc).isoformat(), "container": CONTAINER,
                "image": IMAGE, "image_id": info["Image"], "ports": info["NetworkSettings"]["Ports"],
                "memory_limit_bytes": info["HostConfig"]["Memory"], "cpus_nano": info["HostConfig"]["NanoCpus"],
                "volume": VOLUME, "mysql_version": root_sql("SELECT VERSION();").strip(),
                "grants": root_sql("SHOW GRANTS FOR 'jpj_reader'@'%';\nSHOW GRANTS FOR 'jpj_writer'@'%';").strip()}
    (ARTIFACTS / "mysql_runtime.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("action", choices=["start", "stop", "status"])
    action = p.parse_args().action
    if action == "start": start()
    elif action == "stop": print(docker("stop", CONTAINER).stdout.strip())
    else: print(docker("ps", "-a", "--filter", f"name=^{CONTAINER}$", "--format", "{{.Names}} {{.Status}} {{.Ports}}").stdout)
