"""Run after git add: manifest of tracked distributable files, excluding itself."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    from stenograph import __version__
    from stenograph.updates import validate_manifest

    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    files = {}
    for name in names:
        if not name or name == 'release.json':
            continue
        files[name] = hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    manifest = validate_manifest({'app_id': 'stenograph-local', 'version': __version__, 'files': files})
    (ROOT/'release.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f"Release {__version__}: {len(files)} files")


if __name__ == '__main__':
    main()
