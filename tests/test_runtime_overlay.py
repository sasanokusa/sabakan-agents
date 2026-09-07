import tempfile
import unittest
from pathlib import Path
from evaluation.runtime_overlay import with_runtime_overlay
from scripts.download_models import sha256


class RuntimeOverlayTests(unittest.TestCase):
    def test_verified_overlay_keeps_existing_limits_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('llama-server', 'libllama.so'):
                (root / name).write_bytes(b'verified')
            overlay = {'bin_directory': tmp, 'sha256': {p.name: sha256(p) for p in root.iterdir()}}
            command = ['docker', 'run', '-d', '--memory', '8g', '--device', '/dev/nvidia0',
                       '-e', 'LD_LIBRARY_PATH=/original', 'pinned-image', '-m', '/model']
            result = with_runtime_overlay(command, overlay)
            self.assertIn('8g', result)
            self.assertIn('/dev/nvidia0', result)
            self.assertIn('LD_LIBRARY_PATH=/sabakan-runtime:/original', result)
            self.assertNotIn('--entrypoint', command)
            (root / 'libllama.so').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                with_runtime_overlay(command, overlay)

    def test_unknown_shared_library_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'llama-server').write_bytes(b'x')
            overlay = {'bin_directory': tmp, 'sha256': {'llama-server': sha256(root / 'llama-server')}}
            (root / 'extra.so').write_bytes(b'x')
            with self.assertRaisesRegex(ValueError, 'inventory mismatch'):
                with_runtime_overlay([], overlay)
