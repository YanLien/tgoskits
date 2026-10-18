import os, sys, time
from pathlib import Path
root = Path(sys.argv[1])
(root / 'stage1.ready').write_text('ready')
while not (root / 'exec.go').exists():
    time.sleep(0.005)
os.execve(sys.executable, [sys.executable, '-B', str(root / 'stage2.py'), str(root)], dict(os.environ))
