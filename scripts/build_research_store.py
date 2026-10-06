"""Materialize a queryable, attributed SQLite snapshot from verified CSV evidence."""
from __future__ import annotations
import csv
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(destination=None):
    destination = Path(destination or ROOT/'results/research.sqlite')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.building.sqlite')
    if temporary.exists():
        temporary.unlink()
    con = sqlite3.connect(temporary)
    try:
        con.execute('PRAGMA foreign_keys=ON')
        con.executescript('''
        CREATE TABLE source_file (id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, sha256 TEXT NOT NULL, rows INTEGER NOT NULL);
        CREATE TABLE simulation_metric (source_id INTEGER REFERENCES source_file(id), scenario TEXT, split TEXT, fee_bps REAL, policy TEXT, n INTEGER, mean_pnl REAL, rmse REAL, es95 REAL, mean_cost REAL, mean_trades REAL, PRIMARY KEY(scenario,split,fee_bps,policy));
        CREATE TABLE forecast (source_id INTEGER REFERENCES source_file(id), currency TEXT, decision_date TEXT, target_date TEXT, split TEXT, target REAL, train_constant REAL, rolling63 REAL, ewma REAL, ridge REAL, selected REAL, PRIMARY KEY(currency,target_date));
        CREATE TABLE episode (source_id INTEGER REFERENCES source_file(id), currency TEXT, split TEXT, episode_id INTEGER, start_date TEXT, end_date TEXT, strategy TEXT, cost_bps REAL, pnl REAL, cost REAL, gross_replication_pnl REAL, trades INTEGER, PRIMARY KEY(currency,split,episode_id,strategy,cost_bps));
        CREATE INDEX forecast_split ON forecast(currency,split,target_date);
        CREATE INDEX episode_strategy ON episode(currency,split,strategy,cost_bps);
        CREATE VIEW test_risk AS SELECT currency,strategy,cost_bps,count(*) AS episodes,avg(pnl*pnl) AS mean_squared_loss,avg(cost) AS mean_cost FROM episode WHERE split='test' GROUP BY currency,strategy,cost_bps;
        ''')
        tables = {
            'simulation_metrics.csv': ('simulation_metric', ['scenario','split','fee_bps','policy','n','mean_pnl','rmse','es95','mean_cost','mean_trades']),
            'historical_forecasts.csv': ('forecast', ['currency','decision_date','target_date','split','target','train_constant','rolling63','ewma','ridge','selected']),
            'historical_episodes.csv': ('episode', ['currency','split','episode_id','start_date','end_date','strategy','cost_bps','pnl','cost','gross_replication_pnl','trades']),
        }
        counts = {}
        for name,(table,columns) in tables.items():
            path = ROOT/'results'/name
            with path.open(encoding='utf-8',newline='') as handle:
                rows = list(csv.DictReader(handle))
            cursor = con.execute('INSERT INTO source_file(path,sha256,rows) VALUES(?,?,?)',
                                 (f'results/{name}',hashlib.sha256(path.read_bytes()).hexdigest(),len(rows)))
            sid = cursor.lastrowid
            names = ','.join(['source_id']+columns)
            marks = ','.join('?' for _ in range(len(columns)+1))
            con.executemany(f'INSERT INTO {table}({names}) VALUES({marks})',
                            ([sid]+[row[c] for c in columns] for row in rows))
            counts[table] = len(rows)
        con.commit()
        assert con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not con.execute('PRAGMA foreign_key_check').fetchall()
    finally:
        con.close()
    temporary.replace(destination)
    return {'path':str(destination),'tables':counts,'sha256':hashlib.sha256(destination.read_bytes()).hexdigest()}


if __name__ == '__main__':
    print(json.dumps(build(),ensure_ascii=False))
