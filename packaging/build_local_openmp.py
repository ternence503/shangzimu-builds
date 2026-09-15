"""Build only LLVM 18.1.8 OpenMP for Intel macOS; never change an installed app."""
import argparse
import ctypes
import hashlib
import json
import os
import platform
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile

VERSION = '18.1.8'
BASE = 'https://github.com/llvm/llvm-project/releases/download/llvmorg-' + VERSION
SOURCE_HASHES = {
    'openmp': '60ed57245e73894e4a2a89b15889f367bd906abfe6d3f92e1718223d4b496150',
    'cmake': '59badef592dd34893cd319d42b323aaa990b452d05c7180ff20f23ab1b41e837',
}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def unpack(archive, destination):
    """Accept regular files/directories only under the archive's one root."""
    with tarfile.open(archive, 'r:xz') as source:
        members = source.getmembers()
        roots, total = set(), 0
        for item in members:
            path = PurePosixPath(item.name)
            if (path.is_absolute() or not path.parts or '\\' in item.name
                    or '..' in path.parts or not (item.isfile() or item.isdir())):
                raise ValueError('Unsafe source archive member')
            roots.add(path.parts[0])
            total += item.size
        if len(roots) != 1 or total > 150 * 1024 * 1024 or len(members) > 20000:
            raise ValueError('Unexpected source archive layout/size')
        destination.mkdir(parents=True, exist_ok=False)
        source.extractall(destination, members=members, filter='data')
        return destination / roots.pop()


def build(output, source_cache=None):
    if platform.system() != 'Darwin' or platform.machine() != 'x86_64':
        raise RuntimeError('This build target requires Intel macOS')
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError('Fresh output directory required')
    if any(p.is_symlink() for p in output.parents):
        raise ValueError('Symlink output ancestor is not accepted')
    cmake = shutil.which('cmake')
    if not cmake or not shutil.which('make') or not shutil.which('curl'):
        raise RuntimeError('cmake, make and curl are required; use an isolated tool environment')
    output.mkdir(parents=True, exist_ok=False)
    materials = output / 'source-materials'
    materials.mkdir()
    records = []
    for package in ('openmp', 'cmake'):
        filename = package + '-' + VERSION + '.src.tar.xz'
        archive = materials / filename
        original = Path(source_cache) / filename if source_cache else None
        if original and original.is_file() and not original.is_symlink():
            shutil.copyfile(original, archive)
        else:
            subprocess.run(['curl', '--fail', '--location', '--proto', '=https',
                            '--proto-redir', '=https', '--max-time', '180',
                            '--max-filesize', str(20 * 1024 * 1024),
                            BASE + '/' + filename, '-o', str(archive)], check=True)
        if not 0 < archive.stat().st_size < 20 * 1024 * 1024:
            raise ValueError('Unexpected source archive size')
        if sha(archive) != SOURCE_HASHES[package]:
            raise ValueError('Pinned official source archive digest mismatch')
        records.append({'file': filename, 'source_url': BASE + '/' + filename,
                        'sha256': sha(archive),
                        'hash_status': 'locally-computed/from-fixed-official-HTTPS-release-not-independent-signature-verification'})
        expanded = unpack(archive, output / ('extract-' + package))
        expanded.rename(output / package)
    source = output / 'openmp'
    license_file = source / 'LICENSE.TXT'
    if not license_file.is_file() or license_file.is_symlink():
        raise ValueError('Full upstream OpenMP license missing')
    text = license_file.read_text(encoding='utf-8')
    if 'Apache' not in text or 'LLVM Exceptions' not in text:
        raise ValueError('Expected Apache license with LLVM exceptions')
    shutil.copyfile(license_file, materials / 'LLVM-OpenMP-LICENSE.TXT')
    build_dir, install_dir = output / 'build', output / 'install'
    flags = ['-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_OSX_ARCHITECTURES=x86_64',
             '-DCMAKE_OSX_DEPLOYMENT_TARGET=14.0', '-DCMAKE_POLICY_VERSION_MINIMUM=3.5',
             '-DLIBOMP_ENABLE_SHARED=ON', '-DOPENMP_ENABLE_LIBOMPTARGET=OFF',
             '-DOPENMP_ENABLE_OMPT_TOOLS=OFF', '-DLIBOMP_OMPT_SUPPORT=OFF',
             '-DLIBOMP_USE_HWLOC=OFF', '-DLIBOMP_ENABLE_ASSERTIONS=OFF']
    env = os.environ.copy()
    env['MACOSX_DEPLOYMENT_TARGET'] = '14.0'
    subprocess.run([cmake, '-S', str(source), '-B', str(build_dir), '-G', 'Unix Makefiles',
                    '-DCMAKE_INSTALL_PREFIX=' + str(install_dir), *flags], env=env, check=True)
    subprocess.run([cmake, '--build', str(build_dir), '--parallel', '4'], env=env, check=True)
    subprocess.run([cmake, '--install', str(build_dir)], env=env, check=True)
    library = install_dir / 'lib/libomp.dylib'
    if not library.is_file() or not library.resolve().is_relative_to(output):
        raise RuntimeError('Expected built OpenMP dylib missing')
    runtime = ctypes.CDLL(str(library))
    runtime.omp_get_max_threads.restype = ctypes.c_int
    max_threads = runtime.omp_get_max_threads()
    fork_available = bool(getattr(runtime, '__kmpc_fork_call', None))
    if max_threads < 1 or not fork_available:
        raise RuntimeError('OpenMP runtime symbol smoke check failed')
    recipe = {'schema': 1, 'status': 'source-built/runtime-symbol-smoke-tested/not-Torch-ABI-verified',
              'target': 'macOS-x86_64', 'deployment_target': '14.0', 'version': VERSION,
              'sources': records, 'cmake_flags': flags,
              'commands': ['cmake -S openmp -B build -G Unix Makefiles -DCMAKE_INSTALL_PREFIX=install [cmake_flags]',
                           'cmake --build build --parallel 4', 'cmake --install build'],
              'cmake_version': subprocess.check_output([cmake, '--version'], text=True).splitlines()[0],
              'compiler_version': subprocess.check_output(['cc', '--version'], text=True).splitlines()[0],
              'library': {'relative_path': library.relative_to(output).as_posix(), 'sha256': sha(library)},
              'license': {'file': 'LLVM-OpenMP-LICENSE.TXT', 'sha256': sha(materials / 'LLVM-OpenMP-LICENSE.TXT')},
              'smoke': {'omp_get_max_threads': max_threads, '__kmpc_fork_call': fork_available},
              'pending': ['Torch frozen ABI/inference must be verified after replacing its runtime',
                          'Record loader/signature changes and final installed-library SHA separately']}
    with (materials / 'build-recipe.json').open('x', encoding='utf-8') as stream:
        json.dump(recipe, stream, ensure_ascii=False, indent=2)
    return recipe


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--source-cache', type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.source_cache), ensure_ascii=False, indent=2))
