"""Read-only parameterized query of the evidence store, with bounded output."""
import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def query(currency='USD', fee=5.0):
    if currency not in {'USD','JPY'} or fee not in {0.,5.,10.}:
        raise ValueError('currency must be USD/JPY and fee must be 0/5/10 bps')
    uri = (ROOT/'results/research.sqlite').as_uri()+'?mode=ro'
    with sqlite3.connect(uri,uri=True) as con:
        con.row_factory = sqlite3.Row
        return [dict(row) for row in con.execute(
            'SELECT * FROM test_risk WHERE currency=? AND cost_bps=? ORDER BY mean_squared_loss LIMIT 20',
            (currency,fee))]


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--currency',choices=['USD','JPY'],default='USD');p.add_argument('--fee',type=float,default=5.)
    a=p.parse_args();print(json.dumps(query(a.currency,a.fee),ensure_ascii=False,indent=2))
