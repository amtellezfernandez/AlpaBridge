"""The public native CLI must stay usable without private or GPU dependencies."""
import os
from pathlib import Path
import subprocess
import sys


def test_native_configuration_imports_without_benchstudio_or_models():
    source = Path(__file__).resolve().parents[1] / "src"
    code = '''
import importlib.abc
import sys
class DenyNativeImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"benchstudio", "torch", "jax", "alpasim", "grpc"}:
            raise ImportError("forbidden test import: " + fullname)
sys.meta_path.insert(0, DenyNativeImports())
from alpabridge.cli.commands.run_alpasim_scene_batch import _build_parser
from alpabridge.benchstudio import AlpaSimPipeline
assert _build_parser().parse_args(["--model", "route_following"]).executor == "subprocess"
'''
    subprocess.run([sys.executable, "-c", code], check=True,
                   env={**os.environ, "PYTHONPATH": str(source)}, capture_output=True, text=True)
