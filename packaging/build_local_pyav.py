"""Build PyAV against our no-external-codec FFmpeg, repair and install its wheel.

Usage: python packaging/build_local_pyav.py --ffmpeg PREFIX --output FRESH_DIR
PREFIX is build_minimal_ffmpeg.py --development-libraries's install directory.
Windows requires the MSVC developer environment (lib.exe, dumpbin.exe, cl.exe).
"""
from pathlib import Path
import argparse
import json
import os
import re
import subprocess
import sys
import tarfile
import zipfile
from license_materials import AV_VERSION, FFMPEG_SHA, digest, fetch

LIBRARIES = ('avformat', 'avcodec', 'avdevice', 'avutil', 'avfilter', 'swscale', 'swresample')


def exports(text):
    names = []
    for line in text.splitlines():
        match = re.match(r'^\s+\d+\s+[0-9A-Fa-f]+\s+[0-9A-Fa-f]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*$', line)
        if match:
            names.append(match.group(1))
    if not names:
        raise ValueError('No DLL exports found')
    return names


def build(prefix, output):
    prefix = prefix.resolve()
    output = output.resolve()
    if output.exists():
        raise ValueError('Use a fresh PyAV build output')
    recipe = json.loads((prefix.parent / 'source-materials' / 'build-recipe.json').read_text(encoding='utf-8'))
    flags = recipe['configure']
    if recipe['source_sha256'] != FFMPEG_SHA or '--disable-gpl' not in flags or '--disable-autodetect' not in flags or '--enable-shared' not in flags:
        raise ValueError('Source-matched minimal shared FFmpeg required')
    output.mkdir(parents=True)
    print('Preparing source-built PyAV 18.1.0 and minimal FFmpeg import libraries', flush=True)
    if os.name == 'nt':
        for library in LIBRARIES:
            candidates = list((prefix / 'bin').glob(library + '-*.dll'))
            if len(candidates) != 1:
                raise ValueError('Exactly one native DLL required: ' + library)
            dll = candidates[0]
            symbols = exports(subprocess.check_output(['dumpbin', '/exports', str(dll)], text=True))
            definition = output / (library + '.def')
            definition.write_text('LIBRARY ' + dll.name + '\nEXPORTS\n' + '\n'.join(symbols) + '\n', encoding='ascii')
            subprocess.run(['lib', '/nologo', '/def:' + str(definition), '/machine:x64',
                            '/out:' + str(prefix / 'lib' / (library + '.lib'))], check=True)
    metadata = json.loads(fetch('https://pypi.org/pypi/av/' + AV_VERSION + '/json'))
    sdist = next(x for x in metadata['urls'] if x['packagetype'] == 'sdist')
    data = fetch(sdist['url'])
    if digest(data) != sdist['digests']['sha256']:
        raise ValueError('PyAV sdist digest mismatch')
    archive = output / sdist['filename']
    archive.write_bytes(data)
    with tarfile.open(archive) as source:
        source.extractall(output, filter='data')
    tree = output / ('av-' + AV_VERSION)
    subprocess.run([sys.executable, '-m', 'pip', 'install', 'Cython', 'setuptools', 'wheel'], check=True)
    environment = dict(os.environ)
    environment['PKG_CONFIG_PATH'] = str(prefix / 'lib' / 'pkgconfig')
    environment['PATH'] = str(prefix / 'bin') + os.pathsep + environment.get('PATH', '')
    environment['DYLD_LIBRARY_PATH'] = str(prefix / 'lib')
    subprocess.run([sys.executable, 'setup.py', '--ffmpeg-dir=' + str(prefix), 'bdist_wheel'],
                   cwd=tree, env=environment, check=True)
    wheels = list((tree / 'dist').glob('*.whl'))
    if len(wheels) != 1:
        raise ValueError('Exactly one source-built PyAV wheel required')
    repaired = output / 'repaired'
    print('Repairing PyAV wheel with minimal FFmpeg native libraries', flush=True)
    if os.name == 'nt':
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'delvewheel'], check=True)
        subprocess.run([sys.executable, '-m', 'delvewheel', 'repair', str(wheels[0]),
                        '--add-path', str(prefix / 'bin'), '-w', str(repaired)], env=environment, check=True)
    else:
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'delocate'], check=True)
        subprocess.run([str(Path(sys.executable).parent / 'delocate-wheel'), '-w', str(repaired), str(wheels[0])],
                       env=environment, check=True)
    results = list(repaired.glob('*.whl'))
    if len(results) != 1:
        raise ValueError('Exactly one dependency-repaired PyAV wheel required')
    wheel = results[0]
    with zipfile.ZipFile(wheel) as zipped:
        natives = [x for x in zipped.namelist() if x.endswith(('.dll', '.dylib'))]
        if not natives or any('x264' in x.lower() or 'x265' in x.lower() for x in natives):
            raise ValueError('Wheel must include minimal FFmpeg and no GPL codec libraries')
    proof = {'schema': 1, 'status': 'source-built-minimal-ffmpeg', 'av_version': AV_VERSION,
             'av_source_sha256': digest(data), 'ffmpeg_source_sha256': FFMPEG_SHA,
             'ffmpeg_configure': flags, 'wheel_filename': wheel.name,
             'wheel_sha256': digest(wheel.read_bytes()), 'native_libraries': natives}
    (output / 'local-pyav-build.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--force-reinstall', '--no-deps', str(wheel)], check=True)
    # Fresh process: never inspect the pre-install av module cached by a caller.
    subprocess.run([sys.executable, '-c',
                    'import av,json,sys; m=av._core.library_meta; '
                    'assert all("--disable-gpl" in v["configuration"] and "--disable-autodetect" in v["configuration"] '
                    'and "--enable-libx264" not in v["configuration"] and "--enable-libx265" not in v["configuration"] '
                    'for v in m.values()); print(json.dumps(m))'], env=environment, check=True)
    print(str(wheel))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.ffmpeg, args.output)
