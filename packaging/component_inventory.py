"""Build-only evidence collection, not redistribution clearance or a bundled SBOM."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

def safe_component(value):
    value = str(value)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,150}", value) or ".." in value:
        raise ValueError("Unsafe component name/version")
    return value

def relative_file(value):
    text = str(value)
    path = PurePosixPath(text)
    if "\\" in text or path.is_absolute() or any(part in ("..", ".") for part in text.split("/")):
        raise ValueError("Unsafe distribution-relative path")
    if not path.parts or any(not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._+-]*", part) for part in path.parts):
        raise ValueError("Unsafe license filename")
    return path

def write_new(path, payload):
    with Path(path).open("xb") as stream:
        stream.write(payload)

def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()

def license_candidate(path):
    text = str(path).replace("\\", "/")
    if not any(part.endswith(".dist-info") for part in text.split("/")):
        return False
    name = text.split("/")[-1].upper()
    return any(name.startswith(prefix) for prefix in ("LICENSE", "LICENCE", "NOTICE", "COPYING"))

def redact_diagnostics(text):
    text = re.sub(r"https?://[^\s]+", "[source-url-not-collected]", str(text))
    text = re.sub(r"(?:[A-Za-z]:[\\/]|/Users/|/home/|/opt/|/usr/local/|/private/|/var/|/tmp/)[^\s\"']+", "[build-path-redacted]", text)
    return re.sub(r"--(?:prefix|bindir|libdir|incdir|datadir|docdir)=[^\s]+", "[build-location-redacted]", text)

def inventory(resources, distributions=None, run=subprocess.run, av_versions=None):
    resources = Path(resources)
    if not resources.is_dir():
        raise ValueError("Existing resources directory required")
    target = resources / "components.json"
    licenses = resources / "licenses" / "python-packages"
    if target.exists() or target.is_symlink() or licenses.exists() or licenses.is_symlink():
        raise FileExistsError("Inventory output already exists; no overwrite")
    if (resources / "licenses").is_symlink():
        raise ValueError("Symlink output directories are not accepted")
    items = []
    # Validate every candidate before creating output; never serialize absolute install paths.
    distributions = list(importlib.metadata.distributions() if distributions is None else distributions)
    seen = set()
    for dist in distributions:
        name = safe_component(dist.metadata.get("Name", ""))
        version = safe_component(dist.version)
        key = name + "-" + version
        if key.lower() in seen:
            raise ValueError("Duplicate distribution name/version")
        seen.add(key.lower())
        paths = [relative_file(item) for item in (dist.files or []) if license_candidate(item)]
        items.append((dist, name, version, key, paths))
    licenses.mkdir(parents=True, exist_ok=False)
    result = {"schema": 1, "status": "inventory-only/not-redistribution-cleared",
              "scope": "all-installed-distributions/build-environment; not proof all components are bundled",
              "runtime": {"python_version": platform.python_version(), "sys_version": redact_diagnostics(sys.version), "python_implementation": platform.python_implementation(),
                          "system": platform.system(), "machine": platform.machine()},
              "pending": ["Map final bundled binaries to components", "Verify corresponding source archives/build recipes",
                          "Review complete license terms and third-party native libraries"],
              "python_packages": [], "tools": [], "model": {"source_origin": "pending-source-archive-mapping"}}
    for dist, name, version, key, paths in items:
        entry = {"name": name, "version": version, "scope": "build-environment/not-confirmed-bundled",
                 "license_metadata": redact_diagnostics(dist.metadata.get("License-Expression") or dist.metadata.get("License") or "unknown"),
                 "source_origin": "pending-source-archive-mapping", "notices": []}
        for path in paths:
            source = Path(dist.locate_file(str(path)))
            source_root = Path(dist.locate_file('.')).resolve()
            if source.is_symlink() or not source.resolve().is_relative_to(source_root):
                raise ValueError("Symlink license files are not accepted")
            payload = source.read_bytes()
            destination = licenses / key / Path(*path.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            write_new(destination, payload)
            entry["notices"].append({"source_relative_distpath": str(path),
                                     "saved_relative_path": destination.relative_to(resources).as_posix(),
                                     "sha256": hashlib.sha256(payload).hexdigest()})
        entry["notice_status"] = "collected-not-reviewed" if entry["notices"] else "missing/pending"
        result["python_packages"].append(entry)
    for name in ("ffmpeg", "ffprobe"):
        binary = resources / "bin" / (name + (".exe" if sys.platform == "win32" else ""))
        tool = {"name": name, "binary_relative_path": binary.relative_to(resources).as_posix(),
                "source_origin": "pending-source-archive-mapping", "sha256": digest(binary), "commands": {}}
        for argument in ("-version", "-buildconf", "-L"):
            completed = run([str(binary), argument], capture_output=True, text=True, timeout=30, check=True)
            # Keep configure/source diagnostics, but redact concrete build/user prefixes.
            output = (completed.stdout or "") + (completed.stderr or "")
            tool["commands"][argument] = redact_diagnostics(output)
        result["tools"].append(tool)
    if av_versions is None:
        try:
            import av
            av_versions = av.library_versions
        except ImportError:
            av_versions = "unavailable/pending"
    result["av_library_versions"] = av_versions
    marker = resources / "models" / "faster-small" / ".model_ready.json"
    if marker.is_file():
        manifest = json.loads(marker.read_text(encoding="utf-8"))
        if manifest.get("schema") != 1:
            raise ValueError("Unexpected model manifest schema")
        for name, record in manifest.get("files", {}).items():
            safe_component(name)
            if not re.fullmatch(r"[a-fA-F0-9]{64}", str(record.get("sha256", ""))):
                raise ValueError("Invalid model digest")
        # Copy only expected schema fields: no unknown metadata/paths from caller.
        result["model"]["manifest_snapshot"] = {"schema": 1, "model": "small", "files": {
            name: {"size": record["size"], "sha256": record["sha256"]} for name, record in manifest["files"].items()}}
        result["model"]["manifest_sha256"] = digest(marker)
        revision = manifest.get('source_revision', '')
        if manifest.get('source_repo') == 'Systran/faster-whisper-small' and re.fullmatch(r'[0-9a-f]{40}', revision):
            result["model"]["source_repo"] = manifest['source_repo']
            result["model"]["source_revision"] = revision
    else:
        result["model"]["manifest_status"] = "missing/pending"
    write_new(target, json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("resources", type=Path)
    inventory(parser.parse_args().resources)
