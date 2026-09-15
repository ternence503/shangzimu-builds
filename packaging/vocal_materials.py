"""Collect and strictly review fixed VocalWorker notices and binary evidence.

Run with the Python environment used to freeze VocalWorker. This collector
never downloads/executes source code or models and never serializes local
absolute installation paths. Unknown versions, notices, or native owners keep
the manifest unreviewed. The destination must not already exist.
"""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
from pathlib import Path, PurePosixPath

MODEL_SHA = 'b62c91cedbc7a066f1778ead5b5cecb377aa3a46a31af1cce7c5c8769339d083'
MODEL_FILE = 'vocals-b62c91ce.pth'
MODEL_SOURCE = 'https://zenodo.org/records/3370489'
NATIVE_SUFFIXES = ('.so', '.dylib', '.dll', '.pyd')
SOX_NATIVE_RE = re.compile(r'(^|[/\\])[^/\\]*sox[^/\\]*(?:\.dll|\.pyd|\.so|\.dylib)$', re.I)
REVIEWED_VERSIONS = {
    'torch': '2.2.2', 'torchaudio': '2.2.2', 'numpy': '1.26.4',
    'openunmix': '1.3.0', 'pyinstaller': '6.22.0',
    'markupsafe': '3.0.3', 'pyyaml': '6.0.3',
}
REQUIRED_NOTICE_HASHES = {
    'torch': {'a11fb738314b6617c6ede596e94f11fc9e260f50487c1c105739056c46e4ef92',
              'c2cc7bf0caec7652c2b460a8a470bea1677f241e4ab8e431df34cf17f5a9fec0'},
    'torchaudio': {'93a58861a858cc108e6b6b833e08e76e8b2a66339e4a8007c8a5a8c1ff9c40d6'},
    'numpy': {'080b68e8f70ebc82c180b7396936172d4331f1a18b17f496b9a9256131712cd8'},
    'openunmix': {'4f7b047ffafb9fbb39a40d605bab961b9b030711addce6e9d23886c2ae3b105e'},
    'pyinstaller': {'dcf75fdb959db1e3b41c0f8505069d2ece781b5ec6b3d0a4d30975cfc6580245'},
}
SOURCE_URLS = {
    'torch': 'https://github.com/pytorch/pytorch/tree/v2.2.2',
    'torchaudio': 'https://github.com/pytorch/audio/tree/v2.2.2',
    'numpy': 'https://github.com/numpy/numpy/tree/v1.26.4',
    'openunmix': 'https://github.com/sigsep/open-unmix-pytorch/tree/v1.3.0',
    'pyinstaller': 'https://github.com/pyinstaller/pyinstaller/tree/v6.22.0',
    'markupsafe': 'https://github.com/pallets/markupsafe/tree/3.0.3',
    'pyyaml': 'https://github.com/yaml/pyyaml/tree/6.0.3',
    'cpython-runtime': 'https://github.com/python/cpython',
    'main-runtime': 'https://github.com/ternence503/shangzimu-builds',
    'llvm-openmp': 'https://github.com/llvm/llvm-project/tree/llvmorg-18.1.8/openmp',
}


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def component(value):
    value = str(value)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,150}', value) or '..' in value:
        raise ValueError('Unsafe distribution identity')
    return value


def relative(value):
    value = str(value).replace('\\', '/')
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(p in ('', '.', '..') for p in value.split('/')):
        raise ValueError('Unsafe distribution-relative filename')
    if any(not re.fullmatch(r'[A-Za-z0-9_.+-]+', p) for p in path.parts):
        raise ValueError('Unsafe distribution-relative filename')
    return path


def notice_candidate(value):
    path = PurePosixPath(str(value).replace('\\', '/'))
    return (any(p.endswith('.dist-info') for p in path.parts)
            and path.name.upper().startswith(('LICENSE', 'LICENCE', 'NOTICE', 'COPYING')))


def safe_file(path, root):
    path, root = Path(path), Path(root).resolve()
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError('Unsafe or missing input material')
    current = path
    while current != root and current != current.parent:
        if current.is_symlink():
            raise ValueError('Symlink material path is not accepted')
        current = current.parent
    return path


def native_owner(path):
    parts = PurePosixPath(path).parts
    if 'iomp' in PurePosixPath(path).name.lower():
        return 'Intel/OpenMP-exact-runtime-review-required'
    if 'torch' in parts or PurePosixPath(path).name.startswith(('libtorch', 'libc10', 'libshm')):
        return 'torch'
    if 'torchaudio' in parts or 'sox' in PurePosixPath(path).name.lower():
        return 'torchaudio/SoX-review-required'
    if 'numpy' in parts or any(x in PurePosixPath(path).name for x in ('openblas', 'gfortran', 'quadmath')):
        return 'numpy/wheel-native-review-required'
    if 'python3.12' in parts or PurePosixPath(path).name.startswith('Python'):
        return 'CPython/runtime-native-review-required'
    return 'unmapped-native-review-required'


def native_payload(path):
    """True for executable/native payloads that need an explicit review map."""
    name = PurePosixPath(path).name
    return name.endswith(NATIVE_SUFFIXES) or name in (
        'VocalWorker', 'VocalWorker.exe', 'Python', 'protoc',
        'protoc-3.13.0.0', 'torch_shm_manager')


def native_set_digest(records):
    canonical = json.dumps(
        [{'path': item['path'], 'sha256': item['sha256']} for item in records],
        ensure_ascii=False, sort_keys=True, separators=(',', ':'),
    ).encode('utf-8')
    return hashlib.sha256(canonical).hexdigest()


def canonical_name(value):
    return re.sub(r'[-_.]+', '-', str(value)).lower()


def reviewed_owner(relative_path, system, has_source_openmp):
    path, name = PurePosixPath(relative_path), PurePosixPath(relative_path).name.lower()
    parts = tuple(part.lower() for part in path.parts)
    if path.name in ('VocalWorker', 'VocalWorker.exe'):
        return 'pyinstaller'
    if ('iomp' in name or name == 'libomp.dylib') and system == 'Darwin' and has_source_openmp:
        return 'llvm-openmp'
    if 'torchaudio' in parts:
        return 'torchaudio'
    if 'torch' in parts or 'functorch' in parts or name.startswith(('libtorch', 'libc10', 'torch_')):
        if ('iomp' in name or name in ('libomp.dylib',)) and system == 'Darwin' and has_source_openmp:
            return 'llvm-openmp'
        return 'torch'
    if 'numpy' in parts or 'numpy.libs' in parts or any(token in name for token in (
            'openblas', 'gfortran', 'quadmath', 'libgcc')):
        return 'numpy'
    if 'markupsafe' in parts:
        return 'markupsafe'
    if 'yaml' in parts:
        return 'pyyaml'
    if ('python3.12' in parts or name.startswith('python') or name.startswith(('_ssl.', '_hashlib.'))
            or name.startswith(('libssl', 'libcrypto', 'libsqlite', 'liblzma', 'libmpdec', 'libffi'))):
        return 'cpython-runtime'
    # These Microsoft redistributables are already present in and reviewed as
    # part of the enclosing Windows runtime.  Keep the mapping explicit rather
    # than treating them as Windows system DLLs.
    if system == 'Windows' and name.startswith(('vcruntime', 'msvcp', 'vcomp')):
        return 'main-runtime'
    return None


def collect(worker, output, models, distributions=None, main_materials=None):
    worker, models, output = Path(worker), Path(models), Path(output)
    if worker.is_symlink() or models.is_symlink() or not worker.is_dir() or not models.is_dir():
        raise ValueError('Existing non-symlink input directories required')
    worker, models = worker.resolve(), models.resolve()
    if output.exists() or output.is_symlink():
        raise FileExistsError('Fresh output directory required; no overwrite')
    for ancestor in output.absolute().parents:
        if ancestor.is_symlink():
            raise ValueError('Symlink output ancestor is not accepted')
    checkpoint = safe_file(models / MODEL_FILE, models)
    if digest(checkpoint) != MODEL_SHA:
        raise ValueError('Official UMX-HQ checkpoint digest mismatch')
    record = json.loads(safe_file(models / 'upstream-record.json', models).read_text(encoding='utf-8'))
    if (record.get('id') != 3370489
            or record.get('metadata', {}).get('license', {}).get('id') != 'mit-license'):
        raise ValueError('Expected official UMX-HQ record and MIT license declaration')
    # Export expected public provenance only, not arbitrary caller metadata.
    model_record = {'record_id': 3370489, 'source_url': MODEL_SOURCE,
                    'license_id': 'mit-license', 'checkpoint': MODEL_FILE,
                    'checkpoint_sha256': MODEL_SHA,
                    'creators': ['Fabian-Robert Stöter', 'Antoine Liutkus'],
                    'copyright_notice': 'Copyright (c) 2019 Inria (Fabian-Robert Stöter, Antoine Liutkus)',
                    'metadata_input_sha256': digest(models / 'upstream-record.json')}
    dist_records, payloads, seen = [], [], set()
    notice_by_package = {}
    model_license = None
    for dist in (importlib.metadata.distributions() if distributions is None else distributions):
        name, version = component(dist.metadata.get('Name', '')), component(dist.version)
        key = name + '-' + version
        if key.lower() in seen:
            raise ValueError('Duplicate distribution identity')
        seen.add(key.lower())
        root = Path(dist.locate_file('')).resolve()
        notices = []
        for original in (dist.files or []):
            if not notice_candidate(original):
                continue
            path = relative(original)
            source = safe_file(dist.locate_file(str(path)), root)
            data = source.read_bytes()
            destination = 'licenses/python-packages/' + key + '/' + str(path)
            notices.append({'path': destination, 'sha256': hashlib.sha256(data).hexdigest()})
            payloads.append((destination, data))
            if name.lower().replace('_', '-') == 'openunmix' and path.name.upper() == 'LICENSE':
                model_license = data
        dist_records.append({'name': name, 'version': version,
                             'scope': 'installed-build-environment/not-confirmed-bundled',
                             'notice_status': 'collected-not-reviewed' if notices else 'missing/pending',
                             'notices': notices})
        notice_by_package[canonical_name(name)] = notices
    if not model_license or b'MIT License' not in model_license or b'Inria' not in model_license:
        raise ValueError('Complete upstream Open-Unmix MIT license required')
    main_names = set()
    main_reviewed = False
    if main_materials:
        main_root = Path(main_materials)
        main_manifest = main_root / 'reviewed-materials-manifest.json'
        if main_manifest.is_file() and not main_manifest.is_symlink():
            main_data = json.loads(main_manifest.read_text(encoding='utf-8'))
            if main_data.get('status') == 'reviewed-for-public-test':
                main_names = {entry.get('path') for entry in main_data.get('files', [])}
                main_reviewed = 'licenses/Python-LICENSE.txt' in main_names
    openmp_source = worker / 'source-materials/llvm-openmp'
    has_source_openmp = openmp_source.is_dir() and not openmp_source.is_symlink()
    if has_source_openmp:
        for original in sorted(openmp_source.rglob('*')):
            if original.is_symlink() or not original.is_file():
                if original.is_symlink():
                    raise ValueError('Symlink LLVM OpenMP material is forbidden')
                continue
            destination = 'licenses/native/llvm-openmp/' + original.relative_to(openmp_source).as_posix()
            payloads.append((destination, original.read_bytes()))
    package_versions = {canonical_name(item['name']): item['version'] for item in dist_records}
    core_ok = all(package_versions.get(name) == version for name, version in REVIEWED_VERSIONS.items())
    hashes_ok = all(REQUIRED_NOTICE_HASHES[name] <= {entry['sha256'] for entry in notice_by_package.get(name, [])}
                    for name in REQUIRED_NOTICE_HASHES)
    numpy_text = b''.join(data for destination, data in payloads if '/numpy-1.26.4/' in destination)
    torch_text = b''.join(data for destination, data in payloads if '/torch-2.2.2/' in destination)
    keyword_ok = (all(word in numpy_text for word in (b'OpenBLAS', b'GCC RUNTIME LIBRARY EXCEPTION', b'libquadmath'))
                  and b'PyTorch' in torch_text and b'Apache License' in torch_text)
    natives = []
    unresolved = []
    for path in sorted(worker.rglob('*')):
        if not native_payload(path.name):
            continue
        if not path.is_file() or not path.resolve().is_relative_to(worker):
            raise ValueError('Native library target escapes worker directory')
        relative_path = path.relative_to(worker).as_posix()
        if SOX_NATIVE_RE.search(relative_path):
            raise ValueError('Native SoX payload is forbidden from the public VocalWorker')
        owner = reviewed_owner(relative_path, platform.system(), has_source_openmp)
        license_paths = []
        if owner in notice_by_package:
            license_paths = [entry['path'] for entry in notice_by_package[owner]]
        elif owner == 'llvm-openmp':
            license_paths = ['licenses/native/llvm-openmp/LLVM-OpenMP-LICENSE.TXT']
        elif owner in ('cpython-runtime', 'main-runtime') and main_reviewed:
            license_paths = ['main-runtime:licenses/Python-LICENSE.txt']
        reviewed = bool(owner and license_paths)
        item = {'path': relative_path, 'sha256': digest(path),
                'mapping_hint': native_owner(relative_path),
                'status': 'reviewed-for-public-test' if reviewed else 'inventory-only/exact-source-and-license-review-pending'}
        if reviewed:
            item.update(owner=owner, source_url=SOURCE_URLS[owner], license_paths=license_paths)
        else:
            unresolved.append(relative_path)
        if path.is_symlink():
            item['symlink_resolved_relative_path'] = path.resolve().relative_to(worker).as_posix()
        natives.append(item)
    review_ok = core_ok and hashes_ok and keyword_ok and main_reviewed and not unresolved
    retained_openmp = any(('iomp' in PurePosixPath(item['path']).name.lower()
                           or PurePosixPath(item['path']).name.lower() == 'libomp.dylib')
                          for item in natives)
    if platform.system() == 'Darwin' and retained_openmp and not has_source_openmp:
        review_ok = False
        unresolved.append('source-materials/llvm-openmp')
    pending = [] if review_ok else [
        'Exact fixed dependency versions, notice hashes, native mappings and main-runtime review must all match',
        *sorted(set(unresolved)),
    ]
    result = {'schema': 1,
              'status': 'reviewed-for-public-test' if review_ok else 'collected-not-reviewed/not-redistribution-cleared',
              'scope': 'final-frozen-vocal-worker',
              'python_packages': dist_records, 'native_files': natives,
              'worker_native_sha256': native_set_digest(natives),
              'model': model_record, 'pending': pending}
    output.mkdir(parents=True, exist_ok=False)
    def save(path, data):
        target = output.joinpath(*relative(path).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(data)
    for path, data in payloads:
        save(path, data)
    save('licenses/UMX-HQ-MIT-LICENSE.txt', model_license)
    save('UMX-HQ-provenance.json', json.dumps(model_record, ensure_ascii=False, indent=2).encode('utf-8'))
    readme = ('VocalWorker 第三方補充材料\n\n'
              '此資料對最終 frozen worker 建立 SHA256、來源及授權對應；未通過時不得公開。\n'
              '模型僅採官方 Zenodo 3370489 明列 MIT 的固定 UMX-HQ vocals 權重。\n'
              'UMX-HQ-MIT-LICENSE.txt 保留上游完整 MIT 與 Inria 作者原文。\n'
              '所有原生檔須有 owner/source/license mapping；任何 SoX 原生檔會直接拒絕。\n'
              '不得沿用字幕主程式的 manifest 冒充涵蓋本 Worker。\n')
    save('THIRD-PARTY-README.txt', readme.encode('utf-8'))
    result['materials'] = [{'path': p.relative_to(output).as_posix(), 'sha256': digest(p)}
                           for p in sorted(output.rglob('*')) if p.is_file()]
    save('vocal-materials-manifest.json', json.dumps(result, ensure_ascii=False, indent=2).encode('utf-8'))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--models', required=True, type=Path)
    parser.add_argument('--main-materials', required=True, type=Path)
    args = parser.parse_args()
    report = collect(args.worker, args.output, args.models, main_materials=args.main_materials)
    print(json.dumps({'status': report['status'], 'packages': len(report['python_packages']),
                      'native_files': len(report['native_files'])}))
