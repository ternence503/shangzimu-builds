"""Collect original third-party materials; collection is NOT a clearance assertion.

The PyAV source recipe is pinned to the release used by av 18.1.0 wheels.
Archives are preserved (never extracted/executed by the collector), with their
upstream SHA256. Keep these files alongside downloadable binaries.
"""
from pathlib import Path, PurePosixPath
import argparse
import ast
import hashlib
import importlib.metadata
import json
import re
import sys
import urllib.request
import zipfile

VENDOR_COMMIT = 'a71bf9279f7a4659154b68ba6783e89be460bcd5'
VENDOR_RAW = 'https://raw.githubusercontent.com/PyAV-Org/pyav-ffmpeg/' + VENDOR_COMMIT
AV_VERSION = '18.1.0'
FFMPEG_SHA = '464beb5e7bf0c311e68b45ae2f04e9cc2af88851abb4082231742a74d97b524c'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_target(root, relative):
    p = PurePosixPath(relative)
    if p.is_absolute() or '..' in p.parts or '\\' in relative or not p.parts:
        raise ValueError('Unsafe material path')
    target = root.joinpath(*p.parts)
    for ancestor in [target, *target.parents]:
        if ancestor == root.parent:
            break
        if ancestor.is_symlink():
            raise ValueError('Symlink material path')
    return target


def fetch(url, maximum=180 * 1024 * 1024):
    if not url.startswith('https://'):
        raise ValueError('Only HTTPS public sources are allowed')
    with urllib.request.urlopen(url, timeout=120) as response:
        if not response.url.startswith('https://'):
            raise ValueError('Insecure redirect')
        data = response.read(maximum + 1)
    if not data or len(data) > maximum:
        raise ValueError('Empty or oversized public material')
    return data


def package_sources(recipe):
    """Parse data only. Never import/execute an upstream build recipe."""
    sources = []
    for node in ast.walk(ast.parse(recipe)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != 'Package':
            continue
        values = {k.arg: k.value.value for k in node.keywords
                  if isinstance(k.value, ast.Constant) and isinstance(k.value.value, str)}
        if {'name', 'source_url', 'sha256'} <= values.keys():
            if not re.fullmatch('[a-f0-9]{64}', values['sha256']):
                raise ValueError('Invalid upstream source digest')
            # Debian's official archive supports HTTPS, unlike the recipe's old URL.
            values['source_url'] = values['source_url'].replace('http://deb.debian.org/', 'https://deb.debian.org/')
            sources.append(values)
    if not sources:
        raise ValueError('No source records in recipe')
    return sources


def review_local_pyav(proof_path):
    if proof_path.is_symlink():
        raise ValueError('Symlink PyAV build proof')
    proof = json.loads(proof_path.read_text(encoding='utf-8'))
    if proof.get('status') != 'source-built-minimal-ffmpeg' or proof.get('av_version') != AV_VERSION or proof.get('ffmpeg_source_sha256') != FFMPEG_SHA:
        raise ValueError('Minimal source-built PyAV proof required')
    filename = proof['wheel_filename']
    if not filename.endswith('.whl') or Path(filename).name != filename or '\\' in filename:
        raise ValueError('Unsafe wheel filename')
    wheel = proof_path.parent / 'repaired' / filename
    if wheel.is_symlink() or digest(wheel.read_bytes()) != proof['wheel_sha256']:
        raise ValueError('Source-built PyAV wheel mismatch')
    import av
    for meta in av._core.library_meta.values():
        configuration = meta['configuration']
        if '--disable-gpl' not in configuration or '--disable-autodetect' not in configuration or any(x in configuration for x in ('--enable-gpl', '--enable-nonfree', '--enable-libx264', '--enable-libx265')):
            raise ValueError('Installed PyAV is not the minimal LGPL build')
    site_root = Path(importlib.metadata.distribution('av').locate_file('')).resolve()
    with zipfile.ZipFile(wheel) as zipped:
        natives = [name for name in zipped.namelist() if name.endswith(('.dll', '.dylib', '.pyd', '.so'))]
        if not natives:
            raise ValueError('Wheel has no native components')
        for relative in natives:
            installed = safe_target(site_root, relative)
            if not installed.is_file() or digest(installed.read_bytes()) != digest(zipped.read(relative)):
                raise ValueError('Installed PyAV native does not match local wheel: ' + relative)
    return proof


def collect(resources, downloader=fetch, local_pyav_build=None, pyav_source_materials=None):
    root = resources.resolve()
    if resources.is_symlink() or not (root / 'components.json').is_file():
        raise ValueError('Fresh inventory required')
    if importlib.metadata.version('av') != AV_VERSION:
        raise ValueError('PyAV version does not match reviewed vendor recipe')
    records = []
    inventory = json.loads((root / 'components.json').read_text(encoding='utf-8'))
    python_version = inventory['runtime']['python_version']
    if not re.fullmatch(r'3\.12\.\d+', python_version):
        raise ValueError('Exact supported runtime Python version required')

    def save(relative, url, expected=None):
        target = safe_target(root, relative)
        data = downloader(url)
        actual = digest(data)
        if expected and actual != expected:
            raise ValueError('Source SHA256 mismatch: ' + relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if not target.is_file() or digest(target.read_bytes()) != actual:
                raise ValueError('Existing material differs: ' + relative)
        else:
            with target.open('xb') as handle:
                handle.write(data)
        records.append({'path': relative, 'sha256': actual, 'source_url': url,
                        'upstream_sha256_verified': expected is not None})
        return data

    if not local_pyav_build:
        recipe = save('licenses/pyav-vendor/pkg.py', VENDOR_RAW + '/scripts/pkg.py')
        save('licenses/source-archives/pyav-ffmpeg-build-recipe.tar.gz',
             'https://codeload.github.com/PyAV-Org/pyav-ffmpeg/tar.gz/' + VENDOR_COMMIT)
        save('licenses/pyav-vendor/build-ffmpeg.py', VENDOR_RAW + '/scripts/build-ffmpeg.py')
        for source in package_sources(recipe.decode('utf-8')):
            filename = source.get('source_filename') or source['source_url'].rsplit('/', 1)[1]
            save('licenses/source-archives/' + source['name'] + '/' + filename,
                 source['source_url'], source['sha256'])
    metadata = json.loads(downloader('https://pypi.org/pypi/av/' + AV_VERSION + '/json'))
    sdist = next(item for item in metadata['urls'] if item['packagetype'] == 'sdist')
    save('licenses/source-archives/' + sdist['filename'], sdist['url'], sdist['digests']['sha256'])
    save('licenses/PyAV-LICENSE.txt',
         'https://raw.githubusercontent.com/PyAV-Org/PyAV/v' + AV_VERSION + '/LICENSE.txt')
    save('licenses/Python-LICENSE.txt',
         'https://raw.githubusercontent.com/python/cpython/v' + python_version + '/LICENSE')
    save('licenses/Silero-VAD-LICENSE.txt',
         'https://raw.githubusercontent.com/snakers4/silero-vad/v6.0/LICENSE')
    save('licenses/Whisper-model-LICENSE.txt',
         'https://raw.githubusercontent.com/openai/whisper/v20250625/LICENSE')
    save('licenses/Whisper-model-card.md',
         'https://huggingface.co/Systran/faster-whisper-small/raw/536b0662742c02347bc0e980a01041f333bce120/README.md')
    vad_source = 'https://raw.githubusercontent.com/SYSTRAN/faster-whisper/v1.2.1/faster_whisper/assets/silero_vad_v6.onnx'
    vad = downloader(vad_source)
    if digest(vad) != '4cbf549b8326f60f80f2536d9eefeb450a9abe83365a098031c89719f1be17d2':
        raise ValueError('Upstream VAD source hash mismatch')
    installed_vad = Path(importlib.metadata.distribution('faster-whisper').locate_file('faster_whisper/assets/silero_vad_v6.onnx'))
    if digest(installed_vad.read_bytes()) != digest(vad):
        raise ValueError('Bundled VAD differs from exact faster-whisper source revision')
    for name in ('tcl', 'tk'):
        save('licenses/' + name + '-license.terms',
             'https://raw.githubusercontent.com/tcltk/' + name + '/core-8-6-branch/license.terms')
    package_versions = {item['name'].lower().replace('_', '-'): item['version'] for item in inventory['python_packages']}
    save('licenses/CTranslate2-LICENSE.txt',
         'https://raw.githubusercontent.com/OpenNMT/CTranslate2/v' + package_versions['ctranslate2'] + '/LICENSE')
    ort_version = package_versions['onnxruntime']
    for filename in ('LICENSE', 'ThirdPartyNotices.txt'):
        save('licenses/ONNXRuntime-' + filename + '.txt',
             'https://raw.githubusercontent.com/microsoft/onnxruntime/v' + ort_version + '/' + filename)
    save('licenses/LLVM-OpenMP-LICENSE.txt',
         'https://raw.githubusercontent.com/llvm/llvm-project/llvmorg-18.1.8/openmp/LICENSE.TXT')
    save('licenses/Tokenizers-LICENSE.txt',
         'https://raw.githubusercontent.com/huggingface/tokenizers/v' + package_versions['tokenizers'] + '/LICENSE')
    save('licenses/FlatBuffers-LICENSE.txt',
         'https://raw.githubusercontent.com/google/flatbuffers/v' + package_versions['flatbuffers'] + '/LICENSE')
    if sys.platform == 'win32':
        save('licenses/GCC-GPLv3.txt',
             'https://raw.githubusercontent.com/gcc-mirror/gcc/releases/gcc-15.2.0/COPYING3')
        save('licenses/GCC-Runtime-Exception.txt',
             'https://raw.githubusercontent.com/gcc-mirror/gcc/releases/gcc-15.2.0/COPYING.RUNTIME')
        save('licenses/MinGW-w64-COPYING.txt',
             'https://raw.githubusercontent.com/mingw-w64/mingw-w64/v13.0.0/COPYING')
        save('licenses/MinGW-w64-AUTHORS.txt',
             'https://raw.githubusercontent.com/mingw-w64/mingw-w64/v13.0.0/AUTHORS')
        save('licenses/source-archives/mingw-w64-v13.0.0.tar.gz',
             'https://codeload.github.com/mingw-w64/mingw-w64/tar.gz/refs/tags/v13.0.0')
    minimal_proof = None
    if local_pyav_build:
        minimal_proof = review_local_pyav(local_pyav_build)
        if not pyav_source_materials or not pyav_source_materials.is_dir():
            raise ValueError('Minimal PyAV FFmpeg source materials required')
        for original in pyav_source_materials.iterdir():
            if original.is_symlink() or not original.is_file():
                raise ValueError('Unsafe PyAV source material')
            relative = 'licenses/pyav-minimal/' + original.name
            target = safe_target(root, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            data = original.read_bytes()
            with target.open('xb') as handle:
                handle.write(data)
            records.append({'path': relative, 'sha256': digest(data), 'source_url': 'local-source-build', 'upstream_sha256_verified': original.name == 'ffmpeg-8.1.2.tar.xz'})
        proof_relative = 'licenses/local-pyav-build.json'
        proof_target = safe_target(root, proof_relative)
        data = local_pyav_build.read_bytes()
        with proof_target.open('xb') as handle:
            handle.write(data)
        records.append({'path': proof_relative, 'sha256': digest(data)})
    report = {'schema': 1, 'status': 'collected-not-reviewed',
              'inventory_sha256': digest((root / 'components.json').read_bytes()),
              'pyav_version': AV_VERSION, 'pyav_vendor_release': '8.1.2-1',
              'pyav_vendor_commit': VENDOR_COMMIT, 'files': records,
              'local_pyav_build': minimal_proof,
              'vad_source': {'source_url': vad_source, 'sha256': digest(vad), 'bundled_sha256_verified': True},
              'pending': ['Map platform wheel native libraries to exact vendor release and compiler-runtime sources',
                          'Map Tcl/Tk binary patch versions to their notices',
                          'Map bundled Silero model SHA to upstream model revision',
                          'CLI tools must be built from the supplied minimal recipe or separately matched to their sources']}
    with safe_target(root, 'license-materials-collection.json').open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    if minimal_proof:
        cli_recipe = json.loads((root / 'licenses' / 'cli-ffmpeg' / 'build-recipe.json').read_text(encoding='utf-8'))
        if cli_recipe.get('source_sha256') != FFMPEG_SHA or '--disable-gpl' not in cli_recipe['configure'] or '--disable-autodetect' not in cli_recipe['configure']:
            raise ValueError('Minimal source-matched command-line tools required')
        for tool in inventory['tools']:
            binary = safe_target(root, tool['binary_relative_path'])
            if digest(binary.read_bytes()) != cli_recipe['tools'][binary.name] or tool['sha256'] != cli_recipe['tools'][binary.name]:
                raise ValueError('CLI inventory does not match source build recipe')
        for original in (root / 'licenses').rglob('*'):
            if original.is_symlink():
                raise ValueError('Symlink third-party material')
            if original.is_file():
                relative = original.relative_to(root).as_posix()
                if relative not in {item['path'] for item in records}:
                    records.append({'path': relative, 'sha256': digest(original.read_bytes())})
        notices = ('上字幕公開測試版：第三方元件與原始授權文件\n'
                   'FFmpeg 8.1.2 CLI 與 PyAV 18.1.0 所連結的 FFmpeg 均由附帶原始碼自行建立，'
                   '未啟用 GPL、nonfree 或外部 codec。FFmpeg 依 LGPL 2.1 or later 提供。\n'
                   'Python、Tcl/Tk、CTranslate2、ONNX Runtime（含其 ThirdPartyNotices）、LLVM/OpenMP、'
                   'Tokenizers、FlatBuffers、Whisper small 與 Silero VAD 原始授權文件在 licenses/；'
                   '其餘 Python 套件原文在 licenses/python-packages/。\n'
                   'FFmpeg 與 PyAV 完整來源、建置設定及變更說明在 licenses/source-archives/、'
                   'licenses/cli-ffmpeg/、licenses/pyav-minimal/，亦隨同 GitHub Releases 提供。\n'
                   '此材料核對針對公開測試版，不表示正式簽署、公證或所有作業系統驗收已完成。\n')
        notice_path = safe_target(root, 'THIRD-PARTY-NOTICES.txt')
        with notice_path.open('x', encoding='utf-8') as handle:
            handle.write(notices)
        records.append({'path': 'THIRD-PARTY-NOTICES.txt', 'sha256': digest(notice_path.read_bytes())})
        manifest = {'schema': 1, 'status': 'reviewed-for-public-test',
                    'inventory_sha256': digest((root / 'components.json').read_bytes()),
                    'review_basis': ['Exact source-built minimal FFmpeg tools hash match',
                                     'Installed PyAV native files match repaired source-built wheel',
                                     'Runtime PyAV configuration rejects GPL/nonfree/external x264/x265',
                                     'Original direct runtime notices collected', 'VAD exact published source hash match'],
                    'files': [{'path': item['path'], 'sha256': item['sha256']} for item in records]}
        with safe_target(root, 'reviewed-materials-manifest.json').open('x', encoding='utf-8') as handle:
            json.dump(manifest, handle, indent=2, ensure_ascii=False)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('resources', type=Path)
    parser.add_argument('--local-pyav-build', type=Path)
    parser.add_argument('--pyav-source-materials', type=Path)
    arguments = parser.parse_args()
    collect(arguments.resources, local_pyav_build=arguments.local_pyav_build,
            pyav_source_materials=arguments.pyav_source_materials)
