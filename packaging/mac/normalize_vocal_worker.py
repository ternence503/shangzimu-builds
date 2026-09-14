"""Preserve one exact OpenMP image instead of a byte-identical unused copy."""
import hashlib
from pathlib import Path
import sys
import subprocess


def prune_unused_sox(worker):
    worker = Path(worker).resolve()
    audio = worker / '_internal/torchaudio'
    # Our worker decodes with the separately audited FFmpeg and uses only
    # TorchAudio's tensor resampler. Confirm its core has no codec dependencies.
    codecs = ('libsox.3.dylib', 'libmad.0.dylib', 'libmp3lame.0.dylib',
              'libmpg123.0.dylib', 'libsndfile.1.0.37.dylib', 'libFLAC.12.dylib',
              'libogg.0.8.5.dylib', 'libvorbis.0.dylib', 'libvorbisenc.2.dylib',
              'libvorbisfile.3.dylib', 'libopus.0.dylib', 'libopusfile.0.dylib',
              'libpng16.16.dylib', 'libz.1.2.13.dylib')
    for name in ('libtorchaudio.so', '_torchaudio.so'):
        core = audio / 'lib' / name
        if core.is_file():
            links = subprocess.check_output(['/usr/bin/otool', '-L', str(core)], text=True)
            if any(codec in links for codec in codecs):
                raise ValueError('Core audio dependency requires optional codec; review before pruning')
    paths = [audio / 'lib' / name for name in ('_torchaudio_sox.so', 'libtorchaudio_sox.so')]
    paths += [audio / '.dylibs' / name for name in codecs]
    for path in paths:
        if not path.exists():
            continue
        target = path.resolve()
        if not target.is_relative_to(worker):
            raise ValueError('Optional backend path escapes generated worker')
        alias = worker / '_internal' / path.name
        if alias.is_symlink() and alias.resolve() == target:
            alias.unlink()
        path.unlink()


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
    prune_unused_sox(sys.argv[1])
