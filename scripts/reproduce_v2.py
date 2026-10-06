"""Reproduce frozen V2 studies without overwriting baseline V1 experiments."""
from __future__ import annotations
import argparse,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--report',action='store_true');args=parser.parse_args()
    scripts=['run_walkforward.py','run_selection_study.py','run_convex_study.py','run_validation.py']
    if args.report:scripts += ['build_v2_figures.py','build_v2_report.py']
    for script in scripts:
        print('Executing '+script,flush=True)
        subprocess.run([sys.executable,str(ROOT/'scripts'/script)],cwd=ROOT,check=True)
    print('V2 numerical reproduction complete. Browser and document rendering are separate recorded checks.')
if __name__=='__main__':main()
