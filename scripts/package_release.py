"""Package the local research release with transparent source counts and hashes."""
from __future__ import annotations
import collections
import hashlib
import json
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CODE_EXT={'.py','.js','.cjs','.css','.html'}
SKIP_DIR={'.git','.venv','venv','__pycache__','.pytest_cache','.work-validation','smoke','browser','build','dist'}


def files():
    return sorted(p for p in ROOT.rglob('*') if p.is_file()
                  and not any(part in SKIP_DIR or part.endswith('.egg-info') for part in p.relative_to(ROOT).parts)
                  and p.suffix not in {'.pyc','.pyo'} and p.name!='MANIFEST.json')


def main():
    counts=collections.defaultdict(lambda:{'files':0,'physical_lines':0,'nonblank_lines_including_comments':0})
    entries=[]
    for path in files():
        relative=path.relative_to(ROOT)
        if path.suffix in CODE_EXT:
            lines=path.read_text(encoding='utf-8').splitlines()
            category=relative.parts[0] if len(relative.parts)>1 else 'root'
            group=counts[category];group['files']+=1;group['physical_lines']+=len(lines)
            group['nonblank_lines_including_comments']+=sum(bool(line.strip()) for line in lines)
            entries.append({'file':relative.as_posix(),'physical_lines':len(lines),'nonblank_lines_including_comments':sum(bool(line.strip()) for line in lines)})
    total={key:sum(v[key] for v in counts.values()) for key in ['files','physical_lines','nonblank_lines_including_comments']}
    count_record={'scope':'Python/JavaScript/CSS/HTML implementation, tests, and reproducible authoring scripts; includes comments; excludes dependencies, data, result tables and generated documents.',
                  'total':total,'categories':dict(counts),'files':entries}
    (ROOT/'results/code_counts.json').write_text(json.dumps(count_record,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest={'version':'2.0.0','algorithm':'SHA-256','excludes':'This manifest itself, caches, virtual environments, QA images and smoke results.',
              'files':{p.relative_to(ROOT).as_posix():{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files()}}
    manifest_path=ROOT/'MANIFEST.json';manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    archive=ROOT.parent/'FinMath_Risk_Lab_研究深化与论文报告_v2.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for path in files()+[manifest_path]:z.write(path,'finmath_risk_lab_v2/'+path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive) as z:
        corrupt=z.testzip()
        if corrupt:raise RuntimeError('Archive CRC failure: '+corrupt)
        for name,record in manifest['files'].items():
            actual=hashlib.sha256(z.read('finmath_risk_lab_v2/'+name)).hexdigest()
            if actual!=record['sha256']:raise RuntimeError('Archive hash mismatch: '+name)
    print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':len(manifest['files'])+1,'code':total},ensure_ascii=False))


if __name__=='__main__':main()
