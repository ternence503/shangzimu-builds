"""Conservative static PE import audit; never borrows the build host's runtimes."""
import argparse
import hashlib
import json
from pathlib import Path
import re

SYSTEM_DLLS = set(('kernel32 kernelbase ntdll user32 gdi32 gdi32full win32u '
    'advapi32 sechost rpcrt4 ole32 oleaut32 combase shell32 shlwapi shcore '
    'comdlg32 msvcrt ucrtbase winmm imm32 version ws2_32 mswsock dnsapi '
    'iphlpapi bcrypt bcryptprimitives ncrypt crypt32 cryptbase cryptsp normaliz '
    'powrprof psapi dbghelp dbgcore winhttp wininet urlmon wtsapi32 userenv '
    'usp10 setupapi cfgmgr32 msimg32 wintrust secur32 sspicli mpr netapi32 '
    'netutils srvcli wkscli authz avrt dwmapi uxtheme propsys sxs mfplat '
    'mfreadwrite mfuuid dxgi d3d9 d3d11 d3d12 dxva2 opengl32 glu32 '
    'avicap32 imagehlp pdh comctl32').split())
# These four imports were observed in the native wheel/FFmpeg audit and
# checked against Microsoft Win32 API Requirements (DLL/minimum Windows):
# capCreateCaptureWindowW, MapAndLoad, PdhOpenQueryW, InitCommonControlsEx.
# They are Windows components, unlike separately installed MSVC runtimes.

def system_import(name):
    lower = name.lower()
    return lower.endswith('.dll') and (lower[:-4] in SYSTEM_DLLS or
        lower.startswith(('api-ms-win-', 'ext-ms-win-')))

def _runtime_roots(bundle, images):
    """Return isolated PyInstaller onedir roots, deepest first.

    A bundled helper such as VocalWorker.exe is a separate process with its own
    sibling ``_internal`` directory.  Windows never searches the parent app's
    ``_internal`` merely because the helper is stored inside that app, so the
    audit must not merge candidates from the two runtimes.
    """
    roots = {bundle}
    for image in images:
        if image.suffix.lower() == '.exe' and (image.parent / '_internal').is_dir():
            roots.add(image.parent)
    return sorted(roots, key=lambda path: len(path.parts), reverse=True)

def _owning_runtime(image, runtime_roots):
    return next(root for root in runtime_roots if image.is_relative_to(root))

def _bundle_path(bundle, path):
    """Stable report path independent of the runner's native separator."""
    return Path(path).relative_to(bundle).as_posix()

def _sha256(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()

def audit_graph(bundle, images, dll_directories=()):
    bundle = Path(bundle).resolve()
    images = {Path(p).resolve(): data for p, data in images.items()}
    runtime_roots = _runtime_roots(bundle, images)
    declared_by_runtime = {root: [] for root in runtime_roots}
    declared = []
    for relative in dll_directories:
        relative = Path(relative)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('DLL directory must be exact bundle-relative path')
        directory = (bundle / relative).resolve()
        if not directory.is_relative_to(bundle) or not directory.is_dir():
            raise ValueError('DLL directory must exist inside bundle')
        runtime = _owning_runtime(directory, runtime_roots)
        declared_by_runtime[runtime].append(directory)
        declared.append(relative.as_posix())
    errors, resolutions = [], []
    for image, data in sorted(images.items()):
        if not image.is_relative_to(bundle):
            errors.append({'reason':'PE image escapes bundle'})
            continue
        if data['machine'] != 0x8664:
            errors.append({'image':_bundle_path(bundle, image), 'reason':'non-x64 PE image'})
        # Parent is the direct DLL loader directory. Additional directories
        # represent explicit PyInstaller runtime hooks scoped to this process.
        # Never borrow DLLs from a separate nested PyInstaller executable.
        runtime = _owning_runtime(image, runtime_roots)
        directories = list(dict.fromkeys(
            [image.parent, runtime, runtime / '_internal'] + declared_by_runtime[runtime]
        ))
        for name in data['imports']:
            if not re.fullmatch(r'[A-Za-z0-9_.+-]+', name):
                errors.append({'image':_bundle_path(bundle, image), 'dependency':name, 'reason':'invalid import name'})
                continue
            if system_import(name):
                continue
            candidates = []
            for directory in directories:
                if not directory.is_dir():
                    continue
                for path in directory.iterdir():
                    if path.name.lower() == name.lower() and path.is_file():
                        candidates.append(path.resolve())
            candidates = list(dict.fromkeys(candidates))
            if not candidates:
                errors.append({'image':_bundle_path(bundle, image), 'dependency':name,
                               'reason':'non-OS dependency not bundled in declared loader directories'})
            elif any(not p.is_relative_to(bundle) or p not in images for p in candidates):
                errors.append({'image':_bundle_path(bundle, image), 'dependency':name,
                               'reason':'external or unaudited candidate'})
            elif len(candidates) != 1:
                candidate_hashes = {_sha256(path) for path in candidates}
                if len(candidate_hashes) != 1:
                    errors.append({'image':_bundle_path(bundle, image), 'dependency':name,
                                   'reason':'ambiguous DLL directory search order'})
                    continue
                resolutions.append({
                    'image':_bundle_path(bundle, image), 'dependency':name,
                    'resolved':_bundle_path(bundle, candidates[0]),
                    'equivalent_candidates':[
                        _bundle_path(bundle, path) for path in candidates
                    ],
                    'sha256':next(iter(candidate_hashes)),
                })
            else:
                resolutions.append({'image':_bundle_path(bundle, image), 'dependency':name,
                                    'resolved':_bundle_path(bundle, candidates[0])})
    return {'status':'passed' if images and not errors else 'needs-review',
            'pe_count':len(images), 'errors':errors, 'resolutions':resolutions,
            'declared_dll_directories':declared,
            'runtime_roots':[path.relative_to(bundle).as_posix() if path != bundle else '.' for path in runtime_roots],
            'limitations':'Static imports and delay imports only. OS core/API-set names assumed available on supported Windows. '
                          'Nested PyInstaller process roots are isolated. DLL directories are caller-declared runtime hooks '
                          'scoped to their owning process; duplicate search order is rejected. '
                          'Does not prove arbitrary LoadLibrary, driver availability or fresh-OS execution. '
                          'MSVC redistributables are not treated as built-in OS libraries.'}

def run(bundle, dll_directories=()):
    import pefile
    bundle = Path(bundle).resolve()
    images = {}
    for path in bundle.rglob('*'):
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            if stream.read(2) != b'MZ':
                continue
        with pefile.PE(str(path), fast_load=True) as pe:
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT'],
                                                  pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT']])
            imports = [entry.dll.decode('ascii') for table in ('DIRECTORY_ENTRY_IMPORT', 'DIRECTORY_ENTRY_DELAY_IMPORT')
                       for entry in getattr(pe, table, [])]
            images[path] = {'machine':pe.FILE_HEADER.Machine, 'imports':list(dict.fromkeys(imports))}
    return audit_graph(bundle, images, dll_directories)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--dll-directory', action='append', default=[])
    args = parser.parse_args()
    report = run(args.bundle, args.dll_directory)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report['status'] == 'passed' else 1)
