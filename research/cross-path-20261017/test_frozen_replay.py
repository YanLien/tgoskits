"""Prove the cold consumer uses archived code and rejects a changed corpus."""
import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

from frozen_replay import restore_sources


class FrozenReplay(unittest.TestCase):
    def test_consumes_archived_sources_and_rejects_changed_corpus(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root/'current'
            current.mkdir()
            (current/'instrument.py').write_text('def measure(value): return 999\n')
            files = {'instrument.py': b'def measure(value): return value+1\n',
                     'consumer.py': b'import instrument; print(instrument.measure(5))\n'}
            expected = {p: hashlib.sha256(data).hexdigest() for p, data in files.items()}
            def package(name, contents):
                path = root/name
                with tarfile.open(path, 'w:gz') as stream:
                    for relative, data in contents.items():
                        member = tarfile.TarInfo(relative)
                        member.size = len(data)
                        stream.addfile(member, io.BytesIO(data))
                return path
            original = package('original.tar.gz', files)
            restored = root/'restored'
            restore_sources(expected, [original], restored)
            done = subprocess.run([sys.executable, str(restored/'consumer.py')], cwd=current,
                                  env=dict(os.environ, PYTHONPATH=str(current)),
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stdout, '6\n')
            altered = package('altered.tar.gz', {**files, 'instrument.py': b'def measure(value): return 999\n'})
            for archives, corpus in (([altered], expected),
                                     ([original], {**expected, 'missing.py': '0'*64})):
                with self.subTest(archives=archives), self.assertRaises(ValueError):
                    restore_sources(corpus, archives, root/('rejected-'+archives[0].stem))


if __name__ == '__main__':
    unittest.main()
