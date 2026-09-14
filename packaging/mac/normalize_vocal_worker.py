"""Preserve one exact OpenMP image instead of a byte-identical unused copy."""
import hashlib
from pathlib import Path
import sys


def normalize(worker):
    worker = Path(worker).resolve()
    duplicate = worker / '_internal/torch/lib/libiomp5.dylib'
    loaded_alias = worker / '_internal/libiomp5.dylib'
    if not duplicate.exists() or not loaded_alias.exists() or duplicate.is_symlink():
        return
    loaded = loaded_alias.resolve()
    if not loaded.is_relative_to(worker) or not duplicate.resolve().is_relative_to(worker) or duplicate.resolve() == loaded:
        raise ValueError('Unexpected OpenMP loader layout')
    if hashlib.sha256(duplicate.read_bytes()).digest() != hashlib.sha256(loaded.read_bytes()).digest():
        raise ValueError('OpenMP copies differ; do not normalize')
    # Keep the package's original path usable. Only the duplicate generated
    # image is replaced; the proven loader target and all libraries remain.
    import os
    relative = os.path.relpath(loaded, duplicate.parent)
    duplicate.unlink()
    duplicate.symlink_to(relative)


if __name__ == '__main__':
    normalize(sys.argv[1])
