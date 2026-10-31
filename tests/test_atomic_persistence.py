"""Atomic persistence survives brief Windows destination-file locks."""
import errno
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'reading-yearbook-skill' / 'scripts'))
from html_contract import atomic_text


def windows_lock():
    error = PermissionError(errno.EACCES, 'destination temporarily busy')
    error.winerror = 5
    return error


class AtomicPersistenceTests(unittest.TestCase):
    def test_transient_windows_lock_retries_same_complete_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'state.json'
            target.write_text('old', encoding='utf-8')
            replace = os.replace
            attempts = []

            def busy_then_replace(source, destination):
                attempts.append(source)
                self.assertEqual(target.read_text('utf-8'), 'old')
                self.assertEqual(Path(source).read_text('utf-8'), '完整的新状态')
                if len(attempts) < 3:
                    raise windows_lock()
                replace(source, destination)

            with patch('html_contract.os.replace', side_effect=busy_then_replace):
                atomic_text(target, '完整的新状态')
            self.assertEqual(target.read_text('utf-8'), '完整的新状态')
            self.assertEqual(len(set(attempts)), 1)
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_permanent_windows_lock_is_bounded_and_preserves_old_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'state.json'
            target.write_text('old', encoding='utf-8')
            calls = []

            def always_busy(*args):
                calls.append(args)
                raise windows_lock()

            with patch('html_contract.os.replace', side_effect=always_busy):
                with self.assertRaises(PermissionError):
                    atomic_text(target, 'new')
            self.assertEqual(len(calls), 4)
            self.assertEqual(target.read_text('utf-8'), 'old')
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_non_windows_permission_failure_is_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'state.json'
            with patch('html_contract.os.replace', side_effect=PermissionError('no permission')) as replace:
                with self.assertRaises(PermissionError):
                    atomic_text(target, 'new')
            self.assertEqual(replace.call_count, 1)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_other_os_failure_is_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('html_contract.os.replace', side_effect=OSError(errno.ENOSPC, 'disk full')) as replace:
                with self.assertRaises(OSError):
                    atomic_text(Path(directory) / 'state.json', 'new')
            self.assertEqual(replace.call_count, 1)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
