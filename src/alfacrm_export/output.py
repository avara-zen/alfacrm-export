"""Из SQLite снимка: csv/<таблица>.csv и report.xlsx для человека."""

import csv
import sqlite3
from pathlib import Path

from openpyxl import Workbook

from .store import tables

LESSON_STATUS = "CASE l.status WHEN 1 THEN 'запланирован' WHEN 2 THEN 'отменён' WHEN 3 THEN 'проведён' END"

# Лист отчёта -> SQL по таблицам снимка. Новый лист — новая пара здесь.
REPORT: dict[str, str] = {
    "Клиенты": f"""
        SELECT c.id, c.name AS "ФИО", CASE c.is_study WHEN 1 THEN 'клиент' ELSE 'лид' END AS "Тип",
               CASE c._removed WHEN 1 THEN 'да' ELSE '' END AS "Удалён",
               ss.name AS "Статус обучения", ls.name AS "Источник",
               c.phone AS "Телефон", c.email AS "Email", c.created_at AS "Создан",
               MIN(CASE WHEN d.is_attend = 1 AND l.status = 3 THEN l.date END) AS "Первый урок",
               MAX(CASE WHEN d.is_attend = 1 AND l.status = 3 THEN l.date END) AS "Последний урок",
               COUNT(CASE WHEN d.is_attend = 1 AND l.status = 3 THEN 1 END) AS "Посещено",
               COUNT(CASE WHEN d.is_attend = 0 AND l.status = 3 THEN 1 END) AS "Пропущено",
               (SELECT SUM(p.income) FROM pay p WHERE p.customer_id = c.id) AS "Оплачено",
               c.balance AS "Баланс"
        FROM customer c
        LEFT JOIN study_status ss ON ss.id = c.study_status_id
        LEFT JOIN lead_source ls ON ls.id = c.lead_source_id
        LEFT JOIN lesson_detail d ON d.customer_id = c.id
        LEFT JOIN lesson l ON l.id = d.lesson_id
        WHERE c.is_study = 1 OR d.id IS NOT NULL
           OR c.id IN (SELECT customer_id FROM pay UNION SELECT customer_id FROM cgi)
        GROUP BY c.id
        ORDER BY c.name""",
    "Посещения": f"""
        SELECT l.date AS "Дата", substr(l.time_from, 12, 5) AS "С", substr(l.time_to, 12, 5) AS "До",
               c.name AS "Клиент", d.customer_id AS "id клиента",
               (SELECT group_concat(g.name, '; ') FROM lesson__group_ids x JOIN groups g ON g.id = x.value
                 WHERE x.lesson_id = l.id) AS "Группа",
               s.name AS "Предмет", l.lesson_type_name AS "Тип урока",
               (SELECT group_concat(t.name, '; ') FROM lesson__teacher_ids x JOIN teacher t ON t.id = x.value
                 WHERE x.lesson_id = l.id) AS "Педагог",
               {LESSON_STATUS} AS "Статус урока",
               CASE d.is_attend WHEN 1 THEN 'да' ELSE 'нет' END AS "Был",
               d.reason_name AS "Причина пропуска", d.grade AS "Оценка",
               tr.name AS "Абонемент", l.topic AS "Тема", l.id AS "id урока"
        FROM lesson_detail d
        JOIN lesson l ON l.id = d.lesson_id
        LEFT JOIN customer c ON c.id = d.customer_id
        LEFT JOIN subject s ON s.id = l.subject_id
        LEFT JOIN customer_tariff ct ON ct.id = d.ctt_id
        LEFT JOIN tariff tr ON tr.id = ct.tariff_id
        ORDER BY l.date, l.time_from, c.name""",
    "Оплаты": """
        SELECT p.document_date AS "Дата", c.name AS "Клиент", p.customer_id AS "id клиента",
               p.payer_name AS "Плательщик", p.income AS "Сумма", p.pay_type_name AS "Тип",
               pa.name AS "Касса", pi.name AS "Статья", p.note AS "Комментарий", p.id
        FROM pay p
        LEFT JOIN customer c ON c.id = p.customer_id
        LEFT JOIN pay_account pa ON pa.id = p.pay_account_id
        LEFT JOIN pay_item pi ON pi.id = p.pay_item_id
        ORDER BY p.document_date""",
    "Группы": """
        SELECT g.name AS "Группа", CASE g._removed WHEN 1 THEN 'да' ELSE '' END AS "Группа удалена",
               c.name AS "Клиент", x.customer_id AS "id клиента",
               x.b_date AS "С", x.e_date AS "По", g.id AS "id группы"
        FROM cgi x
        JOIN groups g ON g.id = x.group_id
        LEFT JOIN customer c ON c.id = x.customer_id
        ORDER BY g.name, x.b_date""",
}


def build(snap: Path) -> None:
    db = sqlite3.connect(snap / "alfacrm.sqlite")
    csv_dir = snap / "csv"
    csv_dir.mkdir(exist_ok=True)
    for t in tables(db):
        # raw_json только в SQLite: в CSV он дублировал бы все колонки и удваивал размер
        cols = [r[1] for r in db.execute(f'PRAGMA table_info("{t}")') if r[1] != "raw_json"]
        quoted = ", ".join(f'"{c}"' for c in cols)
        cur = db.execute(f'SELECT {quoted} FROM "{t}"')
        with open(csv_dir / f"{t}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(d[0] for d in cur.description)
            w.writerows(cur)

    wb = Workbook(write_only=True)
    for sheet, sql in REPORT.items():
        cur = db.execute(sql)
        ws = wb.create_sheet(sheet)
        ws.append([d[0] for d in cur.description])
        for row in cur:
            ws.append(list(row))
    wb.save(snap / "report.xlsx")
    db.close()
