"""Build source-matched command-line tools, without optional external libraries.

Mac: system clang + make. Windows: run in MSYS2 MINGW64 with GCC/make; invoke
that environment's Python and put its bin directory on PATH. No GPL/nonfree
options, network protocols or externally linked codec libraries are enabled.
This does not replace or clear PyAV's separate bundled FFmpeg libraries.
"""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import tarfile
from license_materials import FFMPEG_SHA, digest, fetch


def build(destination, development_libraries=False, source_archive=None):
    destination = destination.resolve()
    if destination.exists():
        raise ValueError('Use a fresh build destination')
    destination.mkdir(parents=True)
    print('Preparing pinned FFmpeg 8.1.2 source archive', flush=True)
    source_data = source_archive.read_bytes() if source_archive else fetch('https://ffmpeg.org/releases/ffmpeg-8.1.2.tar.xz')
    if digest(source_data) != FFMPEG_SHA:
        raise ValueError('FFmpeg source digest mismatch')
    archive = destination / 'ffmpeg-8.1.2.tar.xz'
    archive.write_bytes(source_data)
    with tarfile.open(archive) as source:
        source.extractall(destination, filter='data')
    tree = destination / 'ffmpeg-8.1.2'
    flags = ['--disable-autodetect', '--disable-gpl', '--disable-nonfree',
             '--disable-version3', '--disable-doc', '--disable-debug',
             '--disable-shared', '--enable-static', '--disable-network',
             '--disable-avdevice', '--disable-x86asm',
             '--disable-ffplay', '--enable-ffmpeg', '--enable-ffprobe']
    if os.name == 'nt':
        flags += ['--cc=gcc', '--target-os=mingw32', '--arch=x86_64',
                  '--extra-ldflags=-static']
    if development_libraries:
        flags = [flag for flag in flags if flag not in
                 ('--disable-shared', '--enable-static', '--enable-ffmpeg', '--enable-ffprobe',
                  '--extra-ldflags=-static', '--disable-avdevice')]
        flags += ['--enable-shared', '--disable-static', '--disable-programs',
                  '--prefix=' + str(destination / 'install').replace('\\', '/')]
        if os.name == 'nt':
            flags += ['--extra-ldflags=-static-libgcc']
    print('Configuring minimal FFmpeg build', flush=True)
    subprocess.run(['bash', './configure', *flags], cwd=tree, check=True)
    print('Compiling minimal FFmpeg build', flush=True)
    subprocess.run(['make', '-j', str(min(os.cpu_count() or 2, 4))], cwd=tree, check=True)
    if development_libraries:
        print('Installing minimal shared development libraries', flush=True)
        subprocess.run(['make', 'install'], cwd=tree, check=True)
    tools = destination / 'bin'
    tools.mkdir()
    for name in (() if development_libraries else ('ffmpeg', 'ffprobe')):
        filename = name + ('.exe' if os.name == 'nt' else '')
        shutil.copy2(tree / filename, tools / filename)
        subprocess.run([str(tools / filename), '-version'], check=True)
    notices = destination / 'source-materials'
    notices.mkdir()
    shutil.copy2(archive, notices / archive.name)
    for name in ('COPYING.LGPLv2.1', 'COPYING.GPLv2', 'COPYING.GPLv3', 'COPYING.LGPLv3', 'LICENSE.md'):
        if (tree / name).is_file():
            shutil.copy2(tree / name, notices / name)
    for name in ('config.h', 'ffbuild/config.mak', 'ffbuild/config.log'):
        shutil.copy2(tree / name, notices / Path(name).name)
    (notices / 'build-recipe.json').write_text(json.dumps(
        {'source_url': 'https://ffmpeg.org/releases/ffmpeg-8.1.2.tar.xz',
         'source_sha256': FFMPEG_SHA, 'source_changes': 'none', 'configure': flags,
         'compiler': subprocess.check_output(['gcc' if os.name == 'nt' else 'cc', '--version'], text=True),
         'tools': {p.name: digest(p.read_bytes()) for p in tools.iterdir()}}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--source-archive', type=Path,
                        help='Reuse an existing archive only after verifying its pinned SHA256')
    parser.add_argument('--development-libraries', action='store_true',
                        help='Build no-external-codec shared development libs for a source-built PyAV wheel')
    arguments = parser.parse_args()
    build(arguments.destination, arguments.development_libraries, arguments.source_archive)
