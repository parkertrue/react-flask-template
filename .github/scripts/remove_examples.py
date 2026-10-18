"""Act out README's "Starting a New App" on a checkout: delete the notes
example and the API-status demo, then rewire what plugged them in.

CI's Scaffold job runs this, then the linters and both unit suites, so a
change that couples shared code to an example fails there rather than in a
new app. The account page stands in for the first real feature.

Every edit must match exactly once, or the script stops and names the file:
update it alongside the wiring point. The files edited here are README's
"Where a feature plugs in" list; one outside it is a coupling to remove,
not an edit to add.
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DELETE = [
    'backend/app/notes',
    'backend/tests/unit/notes',
    'backend/tests/integration/notes',
    'backend/migrations/versions/0002_notes.py',
    'frontend/src/features/notes',
    'frontend/src/features/health',
    'frontend/e2e/notes-crud.spec.js',
    'frontend/e2e/api-status.spec.js',
]

EDITS = {
    'backend/app/features.py': [
        ('from app.notes.routes import notes_bp\n', ''),
        ('BLUEPRINTS = [account_bp, auth_bp, health_bp, notes_bp]',
         'BLUEPRINTS = [account_bp, auth_bp, health_bp]'),
    ],
    'frontend/src/routes.jsx': [
        ("import NotesPage from '@/features/notes/NotesPage'\n", ''),
        ("              { path: 'notes', element: <NotesPage /> },\n", ''),
    ],
    'frontend/src/__tests__/routes.test.jsx': [
        ("vi.mock('@/features/notes/NotesPage', () => ({ default: () => <p>Notes page</p> }))\n", ''),
        ("    ['/notes', 'Login page'],\n", ''),
        ("    ['/notes', 'Notes page'],\n", ''),
        ("    ['/login', 'Notes page'],\n", "    ['/login', 'Account page'],\n"),
        ("    ['/register', 'Notes page'],\n", "    ['/register', 'Account page'],\n"),
    ],
    'frontend/src/auth/GuestRoute.jsx': [
        ("export const AFTER_LOGIN_PATH = '/notes'", "export const AFTER_LOGIN_PATH = '/account'"),
    ],
    'frontend/src/components/layout/Navbar.jsx': [
        ("""          {isAuthenticated ? (
            <NavLink to="/notes" className="nav-link">My notes</NavLink>
          ) : (
            <>
""", """          {!isAuthenticated && (
            <>
"""),
    ],
    'frontend/src/components/layout/__tests__/Navbar.test.jsx': [
        ("expect(links()).toEqual({ Home: '/', 'My notes': '/notes' })",
         "expect(links()).toEqual({ Home: '/' })"),
        ("    ['/notes', ['My notes']],\n", ''),
    ],
    'frontend/src/pages/HomePage.jsx': [
        ("import ApiStatus from '@/features/health/ApiStatus'\n", ''),
        ('        <ApiStatus />\n', ''),
        ('<Link to="/notes" className="btn btn-primary">View my notes</Link>',
         '<Link to="/account" className="btn btn-primary">Your account</Link>'),
    ],
    'frontend/src/pages/__tests__/HomePage.test.jsx': [
        ("import { describe, it, expect, vi } from 'vitest'",
         "import { describe, it, expect } from 'vitest'"),
        ("vi.mock('@/features/health/ApiStatus', () => ({ default: () => null }))\n", ''),
        ("expect(links()).toEqual({ 'View my notes': '/notes' })",
         "expect(links()).toEqual({ 'Your account': '/account' })"),
    ],
}


def main():
    for rel in DELETE:
        path = ROOT / rel
        if path.is_dir():
            shutil.rmtree(path)
        elif path.is_file():
            path.unlink()
        else:
            sys.exit(f'{rel}: not found; update DELETE in {Path(__file__).name}')

    for rel, edits in EDITS.items():
        path = ROOT / rel
        raw = path.read_bytes().decode('utf-8')
        newline = '\r\n' if '\r\n' in raw else '\n'
        text = raw.replace('\r\n', '\n')
        for old, new in edits:
            count = text.count(old)
            if count != 1:
                sys.exit(f'{rel}: expected 1 match, found {count}, of:\n{old}')
            text = text.replace(old, new)
        path.write_bytes(text.replace('\n', newline).encode('utf-8'))

    sys.stdout.write(f'Deleted {len(DELETE)} paths and rewired {len(EDITS)} files\n')


if __name__ == '__main__':
    main()
