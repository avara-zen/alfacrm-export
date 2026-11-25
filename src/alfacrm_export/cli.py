"""alfacrm-export — выгрузка AlfaCRM в SQLite/CSV/XLSX и скачивание записей звонков."""

import argparse
import os
import sys
from pathlib import Path

from . import export, output, recordings
from .api import Api


def load_env(path: Path = Path(".env")) -> None:
    """Переменные из .env; уже заданные в окружении имеют приоритет."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def latest_snapshot(root: Path) -> Path:
    snaps = sorted(p for p in root.glob("*/alfacrm.sqlite") if not (p.parent / "INCOMPLETE").exists())
    if not snaps:
        sys.exit(f"В {root} нет завершённых снимков. Сначала запустите: alfacrm-export export")
    return snaps[-1].parent


def main() -> None:
    load_env()
    p = argparse.ArgumentParser(prog="alfacrm-export", description=__doc__)
    p.add_argument("--data", type=Path, default=Path("data"), help="каталог со снимками (по умолчанию data)")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("export", help="полная выгрузка в новый снимок data/<дата-время>/")
    e.add_argument("--branch", type=int, help="id филиала (по умолчанию первый активный)")
    e.add_argument("--rps", type=float, default=4.0, help="запросов в секунду (лимит AlfaCRM — 5)")

    r = sub.add_parser("recordings", help="скачать записи звонков в <снимок>/recordings/ (докачивает недостающее)")
    r.add_argument("snapshot", nargs="?", type=Path, help="каталог снимка (по умолчанию последний)")
    r.add_argument("--workers", type=int, default=8, help="параллельных загрузок")

    o = sub.add_parser("output", help="пересобрать CSV и report.xlsx из SQLite снимка")
    o.add_argument("snapshot", nargs="?", type=Path, help="каталог снимка (по умолчанию последний)")

    a = p.parse_args()
    if a.cmd == "export":
        missing = [k for k in ("ALFACRM_HOST", "ALFACRM_EMAIL", "ALFACRM_API_KEY") if not os.environ.get(k)]
        if missing:
            sys.exit(f"Не заданы переменные: {', '.join(missing)} (в .env или окружении)")
        api = Api(os.environ["ALFACRM_HOST"], os.environ["ALFACRM_EMAIL"], os.environ["ALFACRM_API_KEY"], a.rps)
        snap = export.run(api, a.data, a.branch)
        output.build(snap)
        print(snap)
    elif a.cmd == "recordings":
        recordings.download(a.snapshot or latest_snapshot(a.data), a.workers)
    elif a.cmd == "output":
        output.build(a.snapshot or latest_snapshot(a.data))
