"""Build-only, pinned Inno Setup translation; never runs on user machines."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

REVISION = 'cfdf48923178df4b4f040e038b423aa555a61ffc'
BASE = f'https://raw.githubusercontent.com/jrsoftware/issrc/{REVISION}/'
LANGUAGE = BASE + 'Files/Languages/Unofficial/ChineseTraditional.isl'
LANGUAGE_SHA256 = 'ab22b0ebf82969d1c9a7208e0e9f60e5119c0c95b9dacc00eb8e5582c7d3c604'

def prepare(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for filename, url, expected in [('ChineseTraditional.isl', LANGUAGE, LANGUAGE_SHA256),
                                    ('LICENSE.txt', BASE + 'license.txt', None)]:
        data = urllib.request.urlopen(url, timeout=30).read()
        digest = hashlib.sha256(data).hexdigest()
        if expected and digest != expected:
            raise ValueError('Pinned language file integrity check failed')
        if not data:
            raise ValueError('Empty upstream resource')
        with (output / filename).open('xb') as stream:
            stream.write(data)
        records.append({'file':filename, 'source':url, 'sha256':digest})
    with (output / 'sources.json').open('x', encoding='utf-8') as stream:
        json.dump({'project':'Inno Setup', 'version':'6.7.1', 'revision':REVISION,
                   'files':records}, stream, indent=2)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    prepare(parser.parse_args().output)
