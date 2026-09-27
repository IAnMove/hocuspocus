"""Build optional collection archives outside Git from the recorded file catalog."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import quote
import zipfile


def build(source: Path, output: Path, manifest_path: Path, release_base: str):
    manifest = json.loads(manifest_path.read_text())
    files = manifest['files']
    groups = {}
    for name, entry in files.items():
        group = name.split('/')[0] if '/' in name else 'common'
        entry['collection'] = group
        groups.setdefault(group, []).append(name)
    output.mkdir(parents=True, exist_ok=True)
    collections = {}
    for group, names in sorted(groups.items()):
        archive = output / (group + '.zip')
        dependencies = set()
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=3) as bundle:
            for name in sorted(names):
                path = source / name
                data = path.read_bytes()
                if len(data) != files[name]['size'] or hashlib.sha256(data).hexdigest() != files[name]['sha256']:
                    raise ValueError('Source does not match pinned manifest: ' + name)
                bundle.writestr(name, data)
                if path.suffix in {'.json', '.html', '.js', '.css'}:
                    text = data.decode('utf-8')
                    # Only real file references, not links to other galleries.
                    for ref in re.findall(r'/examples/([^\s\"\'<>?#)]+)', text):
                        if ref in files and Path(ref).suffix not in {'.html', '.md'}:
                            dependencies.add(files[ref]['collection'])
        collections[group] = {
            'files': sorted(names), 'dependencies': sorted(dependencies - {group}),
            'size': sum(files[n]['size'] for n in names),
            'archive': {'url': release_base.rstrip('/') + '/' + quote(archive.name),
                        'size': archive.stat().st_size, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()},
        }
        print(group, archive.stat().st_size, flush=True)
    manifest['collections'] = collections
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--release-base', required=True)
    args = parser.parse_args()
    build(args.source, args.output, args.manifest, args.release_base)
