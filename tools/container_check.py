"""Run public checks in an expendable Linux container, without private fixtures."""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

parser=argparse.ArgumentParser()
parser.add_argument('--browser',action='store_true')
parser.add_argument('--report-dir',type=Path,required=True)
args=parser.parse_args()
args.report_dir.mkdir(parents=True,exist_ok=True)
root=Path(tempfile.mkdtemp(prefix='ember-ci-'))
shutil.copytree('/source',root/'work',ignore=shutil.ignore_patterns('.git','build','dist','*.egg-info','__pycache__','.venv'))
work=root/'work';envdir=root/'venv'
log=(args.report_dir/'checks.log').open('w')
steps=[]
def run(command):
 started=time.monotonic()
 result=subprocess.run(command,cwd=work,stdout=log,stderr=subprocess.STDOUT)
 log.flush();steps.append({'command':command,'returncode':result.returncode,'duration_s':round(time.monotonic()-started,2)})
 (args.report_dir/'status.json').write_text(json.dumps({'python':sys.version,'steps':steps},indent=2))
 if result.returncode:raise SystemExit(result.returncode)
run([sys.executable,'-m','venv',str(envdir)])
python=str(envdir/'bin/python')
run([python,'-m','pip','install','--disable-pip-version-check',str(work)+'[full]'])
if args.browser:
 run([python,'-m','pip','install','--disable-pip-version-check','playwright==1.60.0'])
 run([python,'-m','playwright','install','--with-deps','chromium'])
 run([python,'-m','unittest','discover','-s','tests','-p','test_browser.py','-v'])
else:
 run([python,'-m','unittest','discover','-s','tests','-v'])
 run([python,'-m','ember','init',str(root/'example'),'--example'])
 run([python,'-m','ember','check','--workspace',str(root/'example')])
 run([python,'-m','pip','wheel',str(work),'--no-deps','--wheel-dir',str(root/'wheel')])
print(json.dumps({'python':sys.version.split()[0],'browser':args.browser,'steps':len(steps),'passed':True}))
