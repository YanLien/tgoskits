import sys, time
from pathlib import Path
root = Path(sys.argv[1])
(root / 'stage2.ready').write_text('ready')
while not (root / 'exit.go').exists():
    time.sleep(0.005)
sys.exit(23)
