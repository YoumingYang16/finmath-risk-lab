"""Recreate numerical evidence from the archived data without downloading anew."""
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--report',action='store_true',help='also regenerate figures and the manuscript; review conclusions after changing protocols')
    args=parser.parse_args()
    scripts=['run_simulations.py','run_historical.py','benchmark_parallel.py','build_research_store.py','run_validation.py','build_evidence_catalog.py']
    if args.report:scripts.extend(['build_figures.py','build_report.py'])
    for script in scripts:
        print(f'Executing {script}',flush=True)
        subprocess.run([sys.executable,str(ROOT/'scripts'/script)],cwd=ROOT,check=True)
    print('Numerical evidence reproduced. Browser and document layout reviews are separate recorded checks.')


if __name__=='__main__':main()
