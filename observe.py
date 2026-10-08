"""Capture the iPhone screen and read text with macOS Vision."""
import base64
import json
import os
import subprocess
from pathlib import Path
from iphone import request

ROOT = Path(__file__).resolve().parent


def observe(path=None):
    path = Path(path or ROOT / 'screen.png')
    path.write_bytes(base64.b64decode(request('GET', '/screenshot')['value']))
    rows = json.loads(subprocess.check_output(
        [os.getenv('POKEPOKE_OCR', '/tmp/pokepoke-ocr'), str(path)], text=True))
    return rows


if __name__ == '__main__':
    for row in observe():
        print(f"{row['x']:.3f},{row['y']:.3f} {row['text']}")
