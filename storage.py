from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np


class HistoryStore:
    def __init__(self, path: str | Path | None = None):
        if path is None:
            path = os.environ.get("DYNACARD_DB_PATH", "data/history.db")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def _init_db(self):
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS measurements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    well_name TEXT NOT NULL,
                    card_date TEXT NOT NULL,
                    surface_position_json TEXT NOT NULL,
                    surface_load_json TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    downhole_position_json TEXT,
                    downhole_load_json TEXT,
                    summary_json TEXT,
                    source_cards TEXT,
                    source_config TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(well_name, card_date)
                )
                """
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_measurements_well_date "
                "ON measurements(well_name, card_date DESC)"
            )

    def upsert_measurement(
        self,
        well_name: str,
        card_date: str,
        surface_position,
        surface_load,
        config: dict,
        source_cards: str = "",
        source_config: str = "",
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        payload = (
            well_name,
            card_date,
            json.dumps(np.asarray(surface_position, dtype=float).tolist()),
            json.dumps(np.asarray(surface_load, dtype=float).tolist()),
            json.dumps(config, ensure_ascii=False),
            source_cards,
            source_config,
            now,
            now,
        )
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO measurements (
                    well_name, card_date, surface_position_json, surface_load_json,
                    config_json, source_cards, source_config, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(well_name, card_date) DO UPDATE SET
                    surface_position_json=excluded.surface_position_json,
                    surface_load_json=excluded.surface_load_json,
                    config_json=excluded.config_json,
                    source_cards=excluded.source_cards,
                    source_config=excluded.source_config,
                    downhole_position_json=NULL,
                    downhole_load_json=NULL,
                    summary_json=NULL,
                    updated_at=excluded.updated_at
                """,
                payload,
            )

    def save_result(self, measurement_id: int, position, load, summary: dict) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as con:
            con.execute(
                """
                UPDATE measurements
                   SET downhole_position_json=?, downhole_load_json=?, summary_json=?, updated_at=?
                 WHERE id=?
                """,
                (
                    json.dumps(np.asarray(position, dtype=float).tolist()),
                    json.dumps(np.asarray(load, dtype=float).tolist()),
                    json.dumps(summary, ensure_ascii=False),
                    now,
                    measurement_id,
                ),
            )

    def list_wells(self) -> list[str]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT DISTINCT well_name FROM measurements ORDER BY well_name"
            ).fetchall()
        return [r[0] for r in rows]

    def list_measurements(self, well_name: str):
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT id, well_name, card_date, summary_json, created_at, updated_at
                  FROM measurements
                 WHERE well_name=?
                 ORDER BY card_date DESC
                """,
                (well_name,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["summary"] = json.loads(item.pop("summary_json")) if item["summary_json"] else None
            result.append(item)
        return result

    def get_measurement(self, measurement_id: int):
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM measurements WHERE id=?", (measurement_id,)
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["surface_position"] = np.asarray(json.loads(item.pop("surface_position_json")), dtype=float)
        item["surface_load"] = np.asarray(json.loads(item.pop("surface_load_json")), dtype=float)
        item["config"] = json.loads(item.pop("config_json"))
        item["downhole_position"] = (
            np.asarray(json.loads(item.pop("downhole_position_json")), dtype=float)
            if item["downhole_position_json"]
            else None
        )
        item["downhole_load"] = (
            np.asarray(json.loads(item.pop("downhole_load_json")), dtype=float)
            if item["downhole_load_json"]
            else None
        )
        item["summary"] = json.loads(item.pop("summary_json")) if item["summary_json"] else None
        return item

    def pending_ids(self) -> list[int]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT id FROM measurements WHERE downhole_position_json IS NULL ORDER BY well_name, card_date"
            ).fetchall()
        return [int(r[0]) for r in rows]

    def count(self) -> int:
        with self._connect() as con:
            return int(con.execute("SELECT COUNT(*) FROM measurements").fetchone()[0])

    def db_bytes(self) -> bytes:
        # Checkpoint WAL so the main DB contains the latest commits.
        with self._connect() as con:
            con.execute("PRAGMA wal_checkpoint(FULL)")
        return self.path.read_bytes()
