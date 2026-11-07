"""Fail when the docs show a production build that doesn't pull its base images.

CI's Workflows job runs this. Without --pull, a hand-typed build keeps the
python and nginx base images as Docker first pulled them, so their upstream
security fixes never arrive however often the server rebuilds. deploy.sh
passes it; this keeps the commands people copy from the docs doing the same.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = [ROOT / 'README.md', ROOT / 'CLAUDE.md', *sorted((ROOT / 'docs').glob('*.md'))]

# A compose command for .env.prod that builds: `build`, or `up --build`
BUILD = re.compile(r'docker compose\b.*--env-file[= ]\.env\.prod\b.*(\sbuild\b|--build\b)')


def main():
    problems = []
    builds = 0
    for doc in DOCS:
        for number, line in enumerate(doc.read_text(encoding='utf-8').splitlines(), 1):
            if not BUILD.search(line):
                continue
            builds += 1
            if '--pull' not in line:
                problems.append(f'{doc.relative_to(ROOT).as_posix()}:{number}: '
                                f'a production build without --pull')
    sys.stdout.write(''.join(f'::error::{p}\n' for p in problems))
    if problems:
        sys.exit(f'{len(problems)} build command(s) without --pull')
    # A build in a form BUILD misses goes unchecked: finding none means the form changed
    if not builds:
        sys.exit('no production build command found in README.md, CLAUDE.md or docs/: '
                 'has its form changed?')
    sys.stdout.write(f'{builds} documented production builds pull their base images\n')


if __name__ == '__main__':
    main()
