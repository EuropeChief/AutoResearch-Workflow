#!/usr/bin/env python3
"""Refresh explicit source hashes after a reviewed maintenance change, never per task."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    path = root / 'rules/manifest.json'
    manifest = json.loads(path.read_text())
    def digest(relative):
        return hashlib.sha256((root / relative).read_bytes()).hexdigest()
    for row in manifest['sources']:
        row['sha256'] = digest(row['path'])
    manifest['catalog']['sha256'] = digest(manifest['catalog']['path'])
    directories = ('sources/tutorial', 'sources/originals', 'sources/notices',
                   'sources/format-precheck', 'skills/autoresearch-task-qa',
                   'skills/autoresearch-baseline-quality')
    files = sorted({p.relative_to(root).as_posix() for folder in directories
                    for p in (root / folder).rglob('*')
                    if p.is_file() and '__pycache__' not in p.parts})
    manifest['bundled_files'] = [{'path': name, 'sha256': digest(name)} for name in files]
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'sources': len(manifest['sources']), 'files': len(files)}))


if __name__ == '__main__':
    main()
