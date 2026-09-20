from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE = ROOT / "warehouse"
RUNTIME = WAREHOUSE / "runtime" / "mysql-serving"
ARTIFACTS = WAREHOUSE / "artifacts" / "mysql-serving"
SOURCE = WAREHOUSE / "evidence" / "20260917_152407_7272aa"
DATABASE = "jpj_serving"
DATASET = "JPJ car registration transactions"
METRIC = "汽车登记次数，不是销量、批发TIV、进口量或库存；state为办理登记的办公室/门户，不是车主所在地。"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def config():
    path = RUNTIME / "config.json"
    if not path.exists():
        raise RuntimeError("MYSQL_NOT_CONFIGURED: run python -m warehouse.serving.ops start")
    return json.loads(path.read_text(encoding="utf-8"))


def connect(role="reader"):
    cfg = config()
    if role not in {"reader", "writer"}:
        raise ValueError("Unknown database role")
    return pymysql.connect(host=cfg["host"], port=cfg["port"],
        user=cfg[role]["user"], password=cfg[role]["password"], database=DATABASE,
        charset="utf8mb4", autocommit=False, connect_timeout=5,
        read_timeout=15, write_timeout=15, cursorclass=pymysql.cursors.DictCursor)


class QueryError(ValueError):
    def __init__(self, code, message, details=None, status=422):
        super().__init__(message)
        self.code, self.message, self.details, self.status = code, message, details or {}, status

    def payload(self):
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}
