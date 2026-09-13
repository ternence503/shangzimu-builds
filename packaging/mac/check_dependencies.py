"""Read-only loader-context-aware Mach-O closure audit; no binary mutation."""
import argparse
import json
import subprocess
from pathlib import Path

MAGIC = {b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf',
         b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca',
         b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'}
SYSTEM = ('/usr/lib/', '/System/Library/')

def is_macho(path):
    try:
        with path.open('rb') as stream:
            return stream.read(4) in MAGIC
    except OSError:
        return False

def command(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT)

def read_image(path):
    header = command('otool', '-hv', str(path))
    if header.count('Mach header') > 1:
        raise ValueError('Multi-slice Mach-O needs per-architecture audit: ' + str(path))
    types = {kind for kind in ('EXECUTE', 'BUNDLE', 'DYLIB') if kind in header.split()}
    if len(types) != 1:
        raise ValueError('Unknown or conflicting Mach-O file type: ' + str(path))
    links, rpaths, current = [], [], None
    for line in command('otool', '-l', str(path)).splitlines():
        value = line.strip()
        if value.startswith('cmd '):
            current = value[4:]
        elif current == 'LC_RPATH' and value.startswith('path '):
            rpaths.append(value[5:].split(' (offset')[0])
        elif current in ('LC_LOAD_DYLIB', 'LC_LOAD_WEAK_DYLIB', 'LC_REEXPORT_DYLIB',
                         'LC_LOAD_UPWARD_DYLIB', 'LC_LAZY_LOAD_DYLIB') and value.startswith('name '):
            # Weak dependencies are required too; absence is not silently accepted.
            links.append(value[5:].split(' (offset')[0])
    return {'kind':types.pop(), 'links':list(dict.fromkeys(links)),
            'rpaths':list(dict.fromkeys(rpaths))}

def audit_graph(app, images, dynamic_roots=()):
    """Canonical images; never union unrelated loaders' runpaths."""
    app = app.resolve()
    images = {Path(p).resolve():m for p, m in images.items()}
    errors, unresolved, contexts, visited, reached = [], [], [], set(), set()
    executables = sorted(p for p, m in images.items() if m['kind'] == 'EXECUTE')
    main = [p for p in executables if p.parent == app / 'Contents' / 'MacOS']
    declared = set()
    for relative in dynamic_roots:
        relative = Path(relative)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Dynamic root must be an App-relative exact path')
        target = (app / relative).resolve()
        if not target.is_relative_to(app) or target not in images:
            raise ValueError('Dynamic root is not an internal audited Mach-O: ' + str(relative))
        declared.add(target)

    def issue(collection, binary, link, reason, **extra):
        collection.append({'binary':str(binary.relative_to(app)), 'dependency':link,
                           'reason':reason, **extra})

    def expand(value, owner, executable):
        if value == '@loader_path' or value.startswith('@loader_path/'):
            return owner.parent / value[len('@loader_path'):].lstrip('/')
        if value == '@executable_path' or value.startswith('@executable_path/'):
            return executable.parent / value[len('@executable_path'):].lstrip('/')
        if value.startswith('/'):
            return Path(value)
        return None

    def walk(binary, executable, inherited=(), ancestry=()):
        if binary in ancestry:
            return
        metadata = images[binary]
        own = []
        for value in metadata['rpaths']:
            expanded = expand(value, binary, executable)
            if expanded is None:
                issue(unresolved, binary, value, 'unsupported LC_RPATH')
            else:
                own.append(str(expanded.resolve()))
        stack = tuple(dict.fromkeys(own + list(inherited)))
        key = (binary, executable, stack)
        if key in visited:
            return
        visited.add(key); reached.add(binary)
        contexts.append({'binary':str(binary.relative_to(app)),
                         'executable':str(executable.relative_to(app)), 'runpath_stack':list(stack)})
        for link in metadata['links']:
            if link.startswith('/') and str(Path(link).resolve()).startswith(SYSTEM):
                continue
            if link.startswith('/'):
                issue(errors, binary, link, 'non-system absolute dependency')
                continue
            if link.startswith('@rpath/'):
                candidates = [Path(value) / link[len('@rpath/'):] for value in stack]
            else:
                candidate = expand(link, binary, executable)
                candidates = [] if candidate is None else [candidate]
            # Search precedence matters; later internal files cannot rescue an
            # earlier existing external candidate.
            target = next((p.resolve() for p in candidates if p.exists()), None)
            if target is None:
                issue(unresolved, binary, link, 'no candidate in loader ancestry',
                      candidates=[str(p) for p in candidates])
            elif not target.is_relative_to(app):
                issue(errors, binary, link, 'first resolved candidate outside App', target=str(target))
            elif target not in images:
                issue(unresolved, binary, link, 'candidate is not an audited Mach-O', target=str(target))
            else:
                walk(target, executable, stack, ancestry + (binary,))

    for executable in executables:
        walk(executable, executable)
    # Python extension modules are dynamic roots of the main executable only.
    for binary, metadata in sorted(images.items()):
        # Rust/Python extensions can be MH_DYLIB rather than MH_BUNDLE.
        # Only the .so extension convention is an additional dynamic root;
        # ordinary .dylib files remain unestablished until reached by a loader.
        if metadata['kind'] == 'BUNDLE' or binary.suffix == '.so' or binary in declared:
            for executable in main:
                inherited = []
                for value in images[executable]['rpaths']:
                    expanded = expand(value, executable, executable)
                    if expanded is not None:
                        inherited.append(str(expanded.resolve()))
                walk(binary, executable, tuple(inherited))
    for binary in sorted(set(images) - reached):
        issue(unresolved, binary, '', 'no established executable or extension loader chain')
    return {'status':'passed' if images and executables and not errors and not unresolved else 'needs-review',
            'app':str(app), 'macho_count':len(images), 'absolute_or_external_errors':errors,
            'unresolved_dependencies':unresolved, 'audited':contexts,
            'declared_dynamic_roots':[str(p.relative_to(app)) for p in sorted(declared)],
            'limitations':'Static loader ancestry closure; Python MH_BUNDLE/.so roots assumed loaded by main executable. '
                          'Explicit dynamic roots are caller-declared load evidence, not inferred by this audit. '
                          'Does not prove arbitrary dlopen paths, weak-link OS compatibility, clean-OS execution or licenses.'}

def run(app, dynamic_roots=()):
    app = app.resolve()
    if not app.is_dir():
        raise ValueError('App directory does not exist')
    paths, escaped = set(), []
    for path in app.rglob('*'):
        if path.is_file() and is_macho(path):
            canonical = path.resolve()
            if canonical.is_relative_to(app):
                paths.add(canonical)
            else:
                escaped.append({'binary':str(path.relative_to(app)), 'dependency':str(canonical),
                                'reason':'Mach-O symlink escapes App'})
    result = audit_graph(app, {path:read_image(path) for path in sorted(paths)}, dynamic_roots)
    result['absolute_or_external_errors'].extend(escaped)
    if escaped:
        result['status'] = 'needs-review'
    return result

def bootloader_python_root(app):
    """Read the actual PyInstaller archive cookie's dlopen library name."""
    import struct
    from PyInstaller.archive.readers import CArchiveReader
    executable = app / 'Contents' / 'MacOS' / 'ShangZiMu'
    archive = CArchiveReader(str(executable))
    with executable.open('rb') as stream:
        stream.seek(archive._end_offset - archive._COOKIE_LENGTH)
        library = struct.unpack(archive._COOKIE_FORMAT, stream.read(archive._COOKIE_LENGTH))[-1]
    name = library.rstrip(b'\0').decode('utf-8')
    if not name or Path(name).name != name or name in ('.', '..'):
        raise ValueError('Invalid bootloader Python library name')
    return str(Path('Contents') / 'Frameworks' / name)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('app', type=Path)
    parser.add_argument('--dynamic-root', action='append', default=[],
                        help='Exact App-relative dlopen root; caller must establish runtime load evidence')
    parser.add_argument('--pyinstaller', action='store_true',
                        help='Establish the Python dlopen root from the actual executable archive cookie')
    args = parser.parse_args()
    roots = list(args.dynamic_root)
    if args.pyinstaller:
        roots.append(bootloader_python_root(args.app))
    result = run(args.app, roots)
    if args.pyinstaller:
        result['python_root_evidence'] = 'Actual PyInstaller executable archive cookie python_libname'
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['status'] == 'passed' else 1)
