"""Collect VocalWorker notices and binary evidence, NOT redistribution clearance.

Run with the Python environment used to freeze VocalWorker. This collector
never downloads/executes source code or models and never serializes local
absolute installation paths. The destination must not already exist.
"""
import argparse
import hashlib
import importlib.metadata
import json
import re
from pathlib import Path, PurePosixPath

MODEL_SHA = 'b62c91cedbc7a066f1778ead5b5cecb377aa3a46a31af1cce7c5c8769339d083'
MODEL_FILE = 'vocals-b62c91ce.pth'
MODEL_SOURCE = 'https://zenodo.org/records/3370489'
NATIVE_SUFFIXES = ('.so', '.dylib', '.dll', '.pyd')


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


def collect(worker, output, models, distributions=None):
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
    if not model_license or b'MIT License' not in model_license or b'Inria' not in model_license:
        raise ValueError('Complete upstream Open-Unmix MIT license required')
    natives = []
    for path in sorted(worker.rglob('*')):
        if not path.name.endswith(NATIVE_SUFFIXES) and path.name not in ('VocalWorker', 'VocalWorker.exe', 'Python', 'protoc', 'protoc-3.13.0.0', 'torch_shm_manager'):
            continue
        if not path.is_file() or not path.resolve().is_relative_to(worker):
            raise ValueError('Native library target escapes worker directory')
        relative_path = path.relative_to(worker).as_posix()
        item = {'path': relative_path, 'sha256': digest(path),
                'mapping_hint': native_owner(relative_path),
                'status': 'inventory-only/exact-source-and-license-review-pending'}
        if path.is_symlink():
            item['symlink_resolved_relative_path'] = path.resolve().relative_to(worker).as_posix()
        natives.append(item)
    pending = ['Installed distribution list is not a final bundled SBOM',
               'Exact native wheel/build/source correspondence remains unreviewed',
               'Torch libiomp5 Intel/OpenMP exact runtime source and redistribution notice not confirmed',
               'SoX LGPL license, exact source and build/relinking materials not confirmed if libsox is retained',
               'NumPy OpenBLAS/LAPACK/GCC-runtime native mapping and source obligations require review',
               'Other CPython-linked native libraries need exact notices/source mapping',
               'UMX-HQ declaration applies only to pinned 3370489 checkpoint; not UMX-L/UMX research models']
    result = {'schema': 1, 'status': 'collected-not-reviewed/not-redistribution-cleared',
              'scope': 'VocalWorker supplemental materials; does not inherit subtitle-package clearance',
              'python_packages': dist_records, 'native_files': natives,
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
              '此資料為蒐集與 SHA256 清單，不是公開散布授權完成聲明。\n'
              '模型僅採官方 Zenodo 3370489 明列 MIT 的固定 UMX-HQ vocals 權重。\n'
              'UMX-HQ-MIT-LICENSE.txt 保留上游完整 MIT 與 Inria 作者原文。\n'
              '套件清單為安裝建置環境，不能證明全部套件都隨 App 分發。\n'
              'SoX/libiomp5/其他原生庫對應來源及義務仍需核對；詳見 manifest pending。\n'
              '不得沿用舊字幕 small 版 reviewed manifest 宣稱覆蓋本 Worker。\n')
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
    args = parser.parse_args()
    report = collect(args.worker, args.output, args.models)
    print(json.dumps({'status': report['status'], 'packages': len(report['python_packages']),
                      'native_files': len(report['native_files'])}))
