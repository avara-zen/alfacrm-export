"""Запись записей API в SQLite: колонка на каждое поле, исходный JSON, таблицы связей для списков id."""

import json
import sqlite3


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _value(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return v


def write_table(db: sqlite3.Connection, name: str, rows: list[dict], extra: list[dict] | None = None) -> None:
    """Создаёт таблицу `name` заново.

    Колонки — объединение ключей всех записей плюс служебные колонки из `extra`
    (по словарю на запись) и `raw_json` с записью как её вернул API.
    Поле-список скалярных значений (например `teacher_ids`) дополнительно
    раскладывается в таблицу `<name>__<поле>` (`<name>_id`, `value`).
    """
    extra = extra or [{} for _ in rows]
    cols: dict[str, None] = {"id": None}
    for r, x in zip(rows, extra):
        cols.update(dict.fromkeys(r))
        cols.update(dict.fromkeys(x))
    cols = list(cols)

    db.execute(f"DROP TABLE IF EXISTS {_q(name)}")
    db.execute(f"CREATE TABLE {_q(name)} ({', '.join(map(_q, cols))}, raw_json)")
    db.executemany(
        f"INSERT INTO {_q(name)} VALUES ({', '.join('?' * (len(cols) + 1))})",
        ([_value({**r, **x}.get(c)) for c in cols] + [json.dumps(r, ensure_ascii=False)] for r, x in zip(rows, extra)),
    )
    for c in cols:
        if c == "id" or c.endswith("_id"):
            db.execute(f"CREATE INDEX {_q(f'ix_{name}_{c}')} ON {_q(name)} ({_q(c)})")

    for c in cols:
        lists = [(r.get("id"), r[c]) for r in rows if isinstance(r.get(c), list)]
        if not lists or any(isinstance(v, (dict, list)) for _, vs in lists for v in vs):
            continue
        link = f"{name}__{c}"
        db.execute(f"DROP TABLE IF EXISTS {_q(link)}")
        db.execute(f"CREATE TABLE {_q(link)} ({_q(name + '_id')}, value)")
        db.executemany(f"INSERT INTO {_q(link)} VALUES (?, ?)", ((pid, v) for pid, vs in lists for v in vs))
        db.execute(f"CREATE INDEX {_q(f'ix_{link}')} ON {_q(link)} ({_q(name + '_id')})")
        db.execute(f"CREATE INDEX {_q(f'ix_{link}_value')} ON {_q(link)} (value)")


def tables(db: sqlite3.Connection) -> list[str]:
    return [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
