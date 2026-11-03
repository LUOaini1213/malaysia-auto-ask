"""Prepare an already running MySQL 8.4 server for the serving layer.

`ops start` does this for the project's own Docker/WSL container. This entry
point does the same against a server you started yourself, such as the
`services: mysql` container in GitHub Actions:

    JPJ_MYSQL_ROOT_PASSWORD=... python -m warehouse.serving.provision --host 127.0.0.1 --port 3306

It creates the schema, a SELECT-only `jpj_reader` and a DML-only `jpj_writer`
with freshly generated passwords, and writes them to the git-ignored
warehouse/runtime/mysql-serving/config.json. Passwords are never printed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets

import pymysql

from .common import DATABASE, RUNTIME

GRANTS = {"reader": ("jpj_reader", "SELECT"), "writer": ("jpj_writer", "SELECT,INSERT,UPDATE,DELETE")}


def statements(sql: str) -> list[str]:
    body = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    return [part.strip() for part in body.split(";") if part.strip()]


def provision(host: str, port: int, root_password: str) -> dict:
    cfg = {"host": host, "port": port}
    for role, (user, _) in GRANTS.items():
        cfg[role] = {"user": user, "password": secrets.token_hex(24)}
    connection = pymysql.connect(host=host, port=port, user="root", password=root_password,
                                 charset="utf8mb4", autocommit=True, connect_timeout=10)
    try:
        with connection.cursor() as cur:
            for statement in statements(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")):
                cur.execute(statement)
            for role, (user, grants) in GRANTS.items():
                password = cfg[role]["password"]
                cur.execute("CREATE USER IF NOT EXISTS %s@'%%' IDENTIFIED BY %s", (user, password))
                cur.execute("ALTER USER %s@'%%' IDENTIFIED BY %s", (user, password))
                cur.execute(f"GRANT {grants} ON {DATABASE}.* TO %s@'%%'", (user,))
            cur.execute("SELECT VERSION()")
            version = cur.fetchone()[0]
    finally:
        connection.close()
    RUNTIME.mkdir(parents=True, exist_ok=True)
    (RUNTIME / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return {"mysql_version": version, "database": DATABASE, "users": [u for u, _ in GRANTS.values()],
            "config": str((RUNTIME / "config.json").relative_to(RUNTIME.parents[2]).as_posix())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3306)
    args = parser.parse_args()
    root_password = os.environ.get("JPJ_MYSQL_ROOT_PASSWORD")
    if not root_password:
        raise SystemExit("Set JPJ_MYSQL_ROOT_PASSWORD to the root password of the running MySQL server")
    print(json.dumps(provision(args.host, args.port, root_password), indent=2))


if __name__ == "__main__":
    main()
