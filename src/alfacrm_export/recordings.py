"""Скачивание записей звонков по record_url в <снимок>/recordings/<call_id>.mp3."""

import shutil
import sqlite3
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .store import write_table


def _fetch(call_id, url: str, folder: Path) -> dict:
    path = folder / f"{call_id}.mp3"
    row = {"id": call_id, "phone_call_id": call_id, "url": url, "path": str(path.relative_to(folder.parent))}
    if path.exists():
        return {**row, "status": "ok", "bytes": path.stat().st_size}
    tmp = path.with_suffix(".part")
    try:
        with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as f:
            shutil.copyfileobj(resp, f)
    except Exception as e:  # битая ссылка не должна останавливать остальные загрузки
        tmp.unlink(missing_ok=True)
        return {**row, "path": None, "status": f"error: {e}", "bytes": 0}
    size = tmp.stat().st_size
    if size == 0:  # телефония может ответить 200 с пустым телом, если запись удалена
        tmp.unlink()
        return {**row, "path": None, "status": "empty", "bytes": 0}
    tmp.rename(path)
    return {**row, "status": "ok", "bytes": size}


def download(snap: Path, workers: int) -> None:
    folder = snap / "recordings"
    folder.mkdir(exist_ok=True)
    db = sqlite3.connect(snap / "alfacrm.sqlite")
    calls = db.execute("SELECT id, record_url FROM phone_call WHERE record_url IS NOT NULL AND record_url != ''").fetchall()
    print(f"Записей к загрузке: {len(calls)} -> {folder}", file=sys.stderr)
    rows = []
    with ThreadPoolExecutor(workers) as pool:
        for n, row in enumerate(pool.map(lambda c: _fetch(c[0], c[1], folder), calls), 1):
            rows.append(row)
            if n % 250 == 0 or n == len(calls):
                print(f"  {n}/{len(calls)}", file=sys.stderr, flush=True)
    write_table(db, "recording", rows)
    db.commit()
    db.close()
    stats = {}
    for r in rows:
        key = r["status"] if not r["status"].startswith("error") else "error"
        stats[key] = stats.get(key, 0) + 1
    print(f"Итог: {stats}. Ошибочные перекачаются при повторном запуске.", file=sys.stderr)
