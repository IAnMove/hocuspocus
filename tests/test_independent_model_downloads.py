"""Exercise real provisioning logic without importing the GPU runtime."""
import ast
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


class IndependentModelDownloadsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.primary = Path(self.temp.name) / 'primary'
        self.linked = Path(self.temp.name) / 'linked'
        spec = importlib.util.spec_from_file_location('test_locator', ROOT / 'app/shared/utils/files_locator.py')
        self.locator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.locator)
        self.locator.set_checkpoints_paths([str(self.primary), str(self.linked)])
        self.download = Mock()
        namespace = {'os': os, 'fl': self.locator, 'hf_download_with_public_fallback': self.download}
        tree = ast.parse((ROOT / 'app/wgp.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'process_files_def')
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'wgp.py', 'exec'), namespace)
        self.provision = namespace['process_files_def']

    def put(self, root, name):
        path = root / 'minimax_h3/vae' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'existing model')
        return path

    def run_definition(self, independent):
        self.provision(repoId='test/model', revision='pinned', sourceFolderList=['vae'],
                       targetFolderList=['minimax_h3'], fileList=[['video.safetensors', 'audio.safetensors']],
                       independent_files=independent)

    def test_local_variant_does_not_redownload_complete_linked_vaes(self):
        self.put(self.primary, 'experimental-video.safetensors')
        self.put(self.linked, 'video.safetensors')
        self.put(self.linked, 'audio.safetensors')
        self.run_definition(True)
        self.download.assert_not_called()
        self.assertFalse((self.primary / 'minimax_h3/vae/video.safetensors').exists())

    def test_independent_weights_can_be_split_between_roots(self):
        self.put(self.primary, 'video.safetensors')
        self.put(self.linked, 'audio.safetensors')
        self.run_definition(True)
        self.download.assert_not_called()

    def test_only_missing_weight_downloads_into_writable_primary(self):
        existing = self.put(self.linked, 'video.safetensors')
        self.run_definition(True)
        self.download.assert_called_once_with(repo_id='test/model', revision='pinned',
            filename='audio.safetensors', local_dir=str(self.primary / 'minimax_h3'), subfolder='vae')
        self.assertEqual(existing.read_bytes(), b'existing model')

    def test_folder_consumers_still_get_complete_primary_directory(self):
        self.put(self.primary, 'experimental-video.safetensors')
        self.put(self.linked, 'video.safetensors')
        self.put(self.linked, 'audio.safetensors')
        self.run_definition(False)
        self.assertEqual(self.download.call_count, 2)


if __name__ == '__main__':
    unittest.main()
