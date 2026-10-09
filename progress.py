"""Versioned local checkpoint with atomic replacement."""
import json
import os
import tempfile
import time
from pathlib import Path


class ProgressFile:
    def __init__(self, path):
        self.path = Path(path)
        self.previous = None

    def load(self):
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text())
            if not isinstance(data, dict) or data.get('version') != 1:
                raise ValueError('Unsupported checkpoint')
            return data
        except (ValueError, OSError):
            raise RuntimeError('進捗ファイルを読めません。元のファイルは保持しています。確認するか --reset-progress で再探索してください。') from None

    def reset(self):
        if self.path.exists():
            # Retain the last checkpoint for manual recovery.
            os.replace(self.path, self.path.with_suffix('.json.bak'))
        self.previous = None

    def save(self, data):
        record = {'version': 1, **data}
        signature = json.dumps(record, ensure_ascii=False, indent=2)
        if signature == self.previous:
            return
        record['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
        content = json.dumps(record, ensure_ascii=False, indent=2) + '\n'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                             prefix='.progress-', delete=False) as handle:
                name = handle.name
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.path)
            self.previous = signature
        finally:
            if name and os.path.exists(name):
                os.unlink(name)
