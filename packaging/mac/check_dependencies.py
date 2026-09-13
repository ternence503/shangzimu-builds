"""Read-only Mach-O dependency audit; never changes signatures or install names."""
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

def run(app):
    app = app.resolve()
    if not app.is_dir():
        raise ValueError('App directory does not exist')
    executables = app / 'Contents' / 'MacOS'
    binary_paths = sorted(p for p in app.rglob('*') if p.is_file() and is_macho(p))
    errors, unresolved, audited = [], [], []
    for binary in binary_paths:
        links = []
        own_ids = {line.strip() for line in command('otool', '-D', str(binary)).splitlines()
                   if line.startswith(('\t', '    ')) or line.startswith(('@rpath', '@loader_path', '@executable_path', '/'))
                   if not line.endswith(':')}
        for line in command('otool', '-L', str(binary)).splitlines():
            if line.startswith(('\t', '    ')) and ' (compatibility version' in line:
                links.append(line.strip().split(' (compatibility version')[0])
        load = command('otool', '-l', str(binary)).splitlines()
        rpaths = []
        for index, line in enumerate(load):
            if line.strip() == 'cmd LC_RPATH':
                for candidate in load[index+1:index+5]:
                    if candidate.strip().startswith('path '):
                        rpaths.append(candidate.strip()[5:].split(' (offset')[0])
                        break
        def expand(value):
            return Path(value.replace('@loader_path', str(binary.parent))
                             .replace('@executable_path', str(executables)))
        for link in links:
            if link in own_ids:
                continue
            if link.startswith(SYSTEM):
                continue
            if link.startswith('/'):
                errors.append({'binary':str(binary.relative_to(app)), 'dependency':link,
                               'reason':'non-system absolute dependency'})
                continue
            if link.startswith(('@loader_path/', '@executable_path/')):
                candidates = [expand(link)]
            elif link.startswith('@rpath/'):
                suffix = link[len('@rpath/'):]
                candidates = [expand(path) / suffix for path in rpaths]
                # Executable runpaths can be inherited by loaded images. Static audit
                # cannot establish every dyld loading chain; do not silently pass.
                if not candidates:
                    unresolved.append({'binary':str(binary.relative_to(app)), 'dependency':link,
                                       'reason':'no local LC_RPATH; inherited dyld chain requires runtime proof'})
                    continue
            else:
                unresolved.append({'binary':str(binary.relative_to(app)), 'dependency':link,
                                   'reason':'unsupported relative install name'})
                continue
            existing = [path.resolve() for path in candidates if path.exists()]
            if not existing:
                unresolved.append({'binary':str(binary.relative_to(app)), 'dependency':link,
                                   'reason':'no candidate exists', 'candidates':[str(p) for p in candidates]})
            elif not any(path.is_relative_to(app) for path in existing):
                errors.append({'binary':str(binary.relative_to(app)), 'dependency':link,
                               'reason':'resolved dependency outside App'})
        audited.append({'binary':str(binary.relative_to(app)), 'dependencies':len(links), 'rpaths':rpaths})
    return {'status':'passed' if binary_paths and not errors and not unresolved else 'needs-review',
            'app':str(app), 'macho_count':len(binary_paths), 'absolute_or_external_errors':errors,
            'unresolved_dependencies':unresolved, 'audited':audited,
            'limitations':'Static dyld audit only. Does not prove clean-OS execution or licenses.'}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('app', type=Path)
    args = parser.parse_args()
    result = run(args.app)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['status'] == 'passed' else 1)
