"""Retrieve only the pinned official MIT UMX-HQ checkpoint, never user media."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

SHA = 'b62c91cedbc7a066f1778ead5b5cecb377aa3a46a31af1cce7c5c8769339d083'
URL = 'https://zenodo.org/records/3370489/files/vocals-b62c91ce.pth'


def prepare(output, checkpoint=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    destination = output / 'vocals-b62c91ce.pth'
    if checkpoint:
        shutil.copyfile(checkpoint, destination)
    else:
        with urllib.request.urlopen(URL, timeout=120) as source, destination.open('xb') as target:
            shutil.copyfileobj(source, target)
    if hashlib.sha256(destination.read_bytes()).hexdigest() != SHA:
        raise ValueError('Official vocal checkpoint digest mismatch')
    with urllib.request.urlopen('https://zenodo.org/api/records/3370489', timeout=60) as source:
        metadata = json.load(source)
    if metadata.get('metadata', {}).get('license', {}).get('id') != 'mit-license':
        raise ValueError('Official checkpoint license declaration changed; review required')
    (output / 'upstream-record.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    notice = ('Open-Unmix UMX-HQ vocals checkpoint\nCreators: Fabian-Robert Stöter and Antoine Liutkus (Inria).\n'
              'Official record and MIT license declaration: https://zenodo.org/records/3370489\n'
              'Checkpoint SHA256: ' + SHA + '\n'
              'Source code: https://github.com/sigsep/open-unmix-pytorch\n'
              'MIT license permits use, modification and distribution subject to retaining its notice.\n')
    (output / 'MODEL-NOTICE.txt').write_text(notice, encoding='utf-8')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--checkpoint', type=Path)
    args = parser.parse_args()
    prepare(args.output, args.checkpoint)
