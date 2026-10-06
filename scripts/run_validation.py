"""Execute tests and artifact audits and retain machine-readable evidence."""
from __future__ import annotations
import argparse
import datetime
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--scratch',type=Path)
    args=parser.parse_args()
    if args.scratch:
        args.scratch.mkdir(parents=True,exist_ok=True)
        scratch=Path(tempfile.mkdtemp(prefix='validation-',dir=args.scratch))
    else:
        base=ROOT/'.work-validation';base.mkdir(exist_ok=True)
        scratch=Path(tempfile.mkdtemp(prefix='risklab-validation-',dir=base))
    result_dir=ROOT/'results';result_dir.mkdir(exist_ok=True)
    xmlpath=result_dir/'pytest-results.xml'
    command=[sys.executable,'-m','pytest','--basetemp',str(scratch/'pytest'),'--junitxml',str(xmlpath)]
    completed=subprocess.run(command,cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8',errors='replace')
    (result_dir/'pytest-output.txt').write_text(completed.stdout,encoding='utf-8')
    print(completed.stdout)
    suites=ET.parse(xmlpath).getroot().iter('testsuite')
    counts={'tests':0,'failures':0,'errors':0,'skipped':0}
    for suite in suites:
        for name in counts:counts[name]+=int(suite.get(name,0))
    audit=subprocess.run([sys.executable,str(ROOT/'scripts/verify_artifacts.py')],cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8',errors='replace')
    (result_dir/'artifact-audit-output.txt').write_text(audit.stdout,encoding='utf-8');print(audit.stdout)
    audit_v2=subprocess.run([sys.executable,str(ROOT/'scripts/verify_v2_artifacts.py')],cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8',errors='replace')
    (result_dir/'v2-artifact-audit-output.txt').write_text(audit_v2.stdout,encoding='utf-8');print(audit_v2.stdout)
    success=completed.returncode==0 and audit.returncode==0 and audit_v2.returncode==0 and counts['errors']==0 and counts['failures']==0
    paths=sorted(p for folder in ['risklab','scripts','tests','web'] for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in {'.py','.cjs','.js','.css','.html'})
    output={'status':'passed' if success else 'failed','executed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'tests_passed':counts['tests']-counts['failures']-counts['errors']-counts['skipped'],**counts,
            'python_exit_code':completed.returncode,'artifact_audit_exit_code':audit.returncode,'v2_artifact_audit_exit_code':audit_v2.returncode,
            'execution_scope':'Local Windows software and research validation; remote CI not executed',
            'browser_evidence':'results/browser_validation.json','environment':{'python':platform.python_version(),'platform':platform.platform()},
            'source_sha256':{str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
    (result_dir/'validation.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    if not success:raise SystemExit(1)


if __name__=='__main__':main()
