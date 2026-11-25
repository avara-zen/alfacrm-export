"""Полная выгрузка одного филиала в снимок: SQLite, потом CSV и отчёт."""

import datetime as dt
import sqlite3
import sys
from pathlib import Path

from .api import Api
from .store import write_table

# Списочные методы филиала, которые отдают всё за один постраничный проход.
SIMPLE = [
    "subject", "room", "location", "tariff", "study-status", "lead-status", "lead-source",
    "customer-reject", "lead-reject", "discount", "lesson-type", "pay-account", "pay-item",
    "pay-type", "pipeline", "user", "teacher", "regular-lesson", "pay", "task",
    "phone-call", "sms-message", "mail-message", "log",
]
TABLE = {"group": "groups"}  # "group" — ключевое слово SQL, без кавычек не запросить


def table_name(endpoint: str) -> str:
    return TABLE.get(endpoint, endpoint.replace("-", "_"))


def log(msg: str) -> None:
    print(f"{dt.datetime.now():%H:%M:%S} {msg}", file=sys.stderr, flush=True)


def fetch_with_removed(api: Api, path: str, base: dict) -> tuple[list[dict], list[dict]]:
    """removed=1 — все записи вместе с удалёнными, removed=2 — только удалённые (для пометки).
    Без фильтра removed AlfaCRM молча отдаёт только неудалённые."""
    removed = {r["id"] for r in api.paged(path, {**base, "removed": 2})}
    rows = list(api.paged(path, {**base, "removed": 1}))
    return rows, [{"_removed": int(r["id"] in removed)} for r in rows]


def per_parent(api: Api, path: str, key: str, ids: list, extra_query: dict | None = None) -> list[dict]:
    """Метод, который отдаёт данные только по одной сущности за запрос (N+1)."""
    out = []
    for n, pid in enumerate(ids, 1):
        out.extend(api.paged(path, query={**(extra_query or {}), key: pid}))
        if n % 200 == 0 or n == len(ids):
            log(f"  {path}: {n}/{len(ids)}")
    return out


def run(api: Api, out_root: Path, branch: int | None) -> Path:
    snap = out_root / dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    snap.mkdir(parents=True)
    marker = snap / "INCOMPLETE"
    marker.write_text("Выгрузка не завершена. Данные в этом снимке неполные.\n")
    db = sqlite3.connect(snap / "alfacrm.sqlite")
    meta = {"host": api.base, "started_at": dt.datetime.now().isoformat(timespec="seconds")}

    api.login()
    branches = list(api.paged("branch/index"))
    write_table(db, "branch", branches)
    if branch is None:
        branch = next(b["id"] for b in branches if b.get("is_active"))
    meta["branch_id"] = branch
    log(f"Филиал {branch}, снимок {snap}")
    b = f"{branch}/"

    def save(name, rows, extra=None):
        write_table(db, name, rows, extra)
        db.commit()
        log(f"{name}: {len(rows)}")

    for ep in SIMPLE:
        save(table_name(ep), list(api.paged(b + ep + "/index")))

    customers, cx = [], []
    for is_study in (0, 1):
        rows, extra = fetch_with_removed(api, b + "customer/index", {"is_study": is_study})
        customers += rows
        cx += extra
    save("customer", customers, cx)

    groups, gx = fetch_with_removed(api, b + "group/index", {})
    save("groups", groups, gx)

    lessons = []
    for status in (1, 2, 3):  # без status API отдаёт только проведённые
        lessons += api.paged(b + "lesson/index", {"status": status})
    save("lesson", lessons)
    save("lesson_detail", [d for les in lessons for d in les.get("details") or []])

    cgi = per_parent(api, b + "cgi/index", "group_id", [g["id"] for g in groups])
    save("cgi", cgi)
    # Абонементы бывают и у лидов (пробные занятия), поэтому берём всех, кто учился или платил.
    used = {r[0] for r in db.execute("SELECT customer_id FROM lesson_detail UNION SELECT customer_id FROM pay")}
    used |= {x["customer_id"] for x in cgi}
    studied = [c["id"] for c in customers if c.get("is_study") == 1 or c["id"] in used]
    save("customer_tariff", per_parent(api, b + "customer-tariff/index", "customer_id", studied))
    save("communication", per_parent(api, b + "communication/index", "related_id",
                                     [c["id"] for c in customers], {"class": "Customer"}))

    meta["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")
    meta["api_requests"] = api.requests
    write_table(db, "_meta", [{"id": k, "value": v} for k, v in meta.items()])
    db.commit()
    db.close()
    marker.unlink()
    log(f"Готово: {api.requests} запросов")
    return snap
