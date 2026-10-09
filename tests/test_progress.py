import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from progress import ProgressFile


class ProgressFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'progress.json'
        self.progress = ProgressFile(self.path)

    def test_save_and_read_back(self):
        self.progress.save({'cursor': {'difficulty': '中級'}, 'status': 'stopped'})
        restored = ProgressFile(self.path).load()
        self.assertEqual(restored['cursor']['difficulty'], '中級')
        self.assertEqual(restored['version'], 1)
        self.assertIn('updated_at', restored)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_interrupted_replace_keeps_previous_file(self):
        self.progress.save({'cursor': 'old'})
        with patch('progress.os.replace', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                self.progress.save({'cursor': 'new'})
        self.assertEqual(self.progress.load()['cursor'], 'old')
        self.assertEqual(list(self.path.parent.glob('.progress-*')), [])

    def test_corrupt_checkpoint_is_preserved(self):
        self.path.write_text('{broken')
        with self.assertRaisesRegex(RuntimeError, '元のファイルは保持'):
            self.progress.load()
        self.assertEqual(self.path.read_text(), '{broken')

    def test_unknown_version_is_not_silently_ignored(self):
        self.path.write_text(json.dumps({'version': 999}))
        with self.assertRaises(RuntimeError):
            self.progress.load()

    def test_reset_backs_up_previous_progress(self):
        self.progress.save({'cursor': 'old'})
        self.progress.reset()
        self.assertIsNone(self.progress.load())
        backup = self.path.with_suffix('.json.bak')
        self.assertEqual(json.loads(backup.read_text())['cursor'], 'old')
