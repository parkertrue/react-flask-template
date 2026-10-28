"""Fail when the Python or Node versions that CI, the locks and the images use differ.

CI's Workflows job runs this. Each version is written in several files: the
images' base, the one `lock_deps.sh` resolves the locks under, and the
workflows' setup steps. Dependabot bumps only the Dockerfiles, so CI and the
locks could fall behind what ships without anything failing.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ('.github/workflows/ci.yml', '.github/workflows/integration-e2e.yml')

# (tool, [(file, pattern)]): each pattern's group is the version, and every
# match in every file must agree
SOURCES = (
    ('Python', [
        ('backend/Dockerfile', r'^FROM python:(\S+?)-slim'),
        ('backend/lock_deps.sh', r'\bpython:(\S+?)-slim\b'),
        *[(workflow, r'python-version: "([^"]+)"') for workflow in WORKFLOWS],
    ]),
    ('Node', [
        ('nginx/Dockerfile', r'^FROM node:(\S+?)-alpine'),
        *[(workflow, r'node-version: "([^"]+)"') for workflow in WORKFLOWS],
    ]),
)


def versions(sources):
    found = []
    for path, pattern in sources:
        matches = re.findall(pattern, (ROOT / path).read_text(encoding='utf-8'), re.MULTILINE)
        found += [(path, None)] if not matches else [(path, version) for version in matches]
    return found


def main():
    problems = []
    for tool, sources in SOURCES:
        found = versions(sources)
        problems += [f'{path}: no {tool} version found' for path, version in found if version is None]
        seen = {version for _, version in found if version is not None}
        if len(seen) > 1:
            listing = ', '.join(f'{path} {version}' for path, version in found if version is not None)
            problems.append(f'{tool} versions differ: {listing}')
    sys.stdout.write(''.join(f'::error::{p}\n' for p in problems))
    if problems:
        sys.exit(f'{len(problems)} version problem(s)')
    sys.stdout.write('Python and Node versions match\n')


if __name__ == '__main__':
    main()
