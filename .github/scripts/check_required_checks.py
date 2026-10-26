"""Fail when README's list of required status checks and the CI jobs differ.

CI's Workflows job runs this. README names the checks to require on `main`
(Settings > Branches), by job name; a job added to a workflow but not to that
list would never block a merge, and a name left in the list after its job is
gone would block every merge. Nothing else compares the two, so each was
fixed by hand when it drifted.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ('ci.yml', 'integration-e2e.yml')

# A job's own name: four spaces in, under its key under `jobs:`. Steps sit
# deeper, and the workflow's name at the top.
JOB_NAME = re.compile(r'^    name: (.+?)\s*$', re.MULTILINE)
SENTENCE = re.compile(r'require these status checks on `main` \(Settings > Branches\): (.+?)\.$', re.MULTILINE)


def jobs():
    names = []
    for workflow in WORKFLOWS:
        names += JOB_NAME.findall((ROOT / '.github' / 'workflows' / workflow).read_text(encoding='utf-8'))
    return names


def required():
    match = SENTENCE.search((ROOT / 'README.md').read_text(encoding='utf-8'))
    if not match:
        sys.exit('README.md: the sentence listing the required status checks is missing')
    return re.split(r', | and ', match.group(1))


def main():
    found, listed = set(jobs()), set(required())
    problems = [f'job "{name}" is missing from README\'s required checks' for name in sorted(found - listed)]
    problems += [f'README requires "{name}", which no job is named' for name in sorted(listed - found)]
    sys.stdout.write(''.join(f'::error::{p}\n' for p in problems))
    if problems:
        sys.exit(f'{len(problems)} required check(s) differ')
    sys.stdout.write(f'{len(found)} jobs, all required in README\n')


if __name__ == '__main__':
    main()
