# -*- coding: utf-8 -*-
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from malaysia_ask.ask import ask  # noqa: E402
from malaysia_ask.db import seed  # noqa: E402


def main():
    seed()
    q = " ".join(sys.argv[1:]).strip() or "2025全年协会口径TIV哪家第一"
    r = ask(q)
    print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
