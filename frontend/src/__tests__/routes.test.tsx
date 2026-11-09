import { useState } from 'react'
import { describe, it, expect, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import { routes } from '../routes'
import HomePage from '@/pages/HomePage'
import Navbar from '@/components/layout/Navbar'
import { renderRoutes, signIn } from '@/test/router'

// Each page has its own tests; here they only need to say which they are
vi.mock('@/components/layout/Navbar', () => ({ default: vi.fn(() => <nav aria-label="Main">Navbar</nav>) }))
vi.mock('@/pages/HomePage', () => ({ default: vi.fn(() => <p>Home page</p>) }))
vi.mock('@/pages/LoginPage', () => ({ default: () => <p>Login page</p> }))
vi.mock('@/pages/RegisterPage', () => ({ default: () => <p>Register page</p> }))
vi.mock('@/pages/CompleteRegistrationPage', () => ({ default: () => <p>Complete registration page</p> }))
vi.mock('@/pages/AccountPage', () => ({ default: () => <p>Account page</p> }))
vi.mock('@/pages/PrivacyPage', () => ({ default: () => <p>Privacy page</p> }))
vi.mock('@/pages/TermsPage', () => ({ default: () => <p>Terms page</p> }))
vi.mock('@/pages/ContactPage', () => ({ default: () => <p>Contact page</p> }))
vi.mock('@/features/notes/NotesPage', () => ({ default: () => <p>Notes page</p> }))

const page = () => screen.getByRole('main')
const navbar = () => screen.queryByRole('navigation', { name: 'Main' })

// A page that works until the user does something, then crashes
function BreaksOnClick() {
  const [broken, setBroken] = useState(false)
  if (broken) throw new Error('Broken later')
  return <button type="button" onClick={() => setBroken(true)}>Break</button>
}

describe('routes', () => {
  it.each([
    ['/', 'Home page'],
    ['/login', 'Login page'],
    ['/register', 'Register page'],
    ['/register/complete', 'Complete registration page'],
    ['/privacy', 'Privacy page'],
    ['/terms', 'Terms page'],
    ['/contact', 'Contact page'],
    // Guarded: a visitor is sent to log in
    ['/notes', 'Login page'],
    ['/account', 'Login page'],
  ])('show a visitor at %s the %s', (path, expected) => {
    renderRoutes(routes, path)

    expect(page()).toHaveTextContent(expected)
  })

  it.each([
    ['/', 'Home page'],
    ['/notes', 'Notes page'],
    ['/account', 'Account page'],
    ['/privacy', 'Privacy page'],
    ['/terms', 'Terms page'],
    ['/contact', 'Contact page'],
    // A signed-in user has no use for these
    ['/login', 'Notes page'],
    ['/register', 'Notes page'],
    ['/register/complete', 'Notes page'],
  ])('show a signed-in user at %s the %s', (path, expected) => {
    signIn()
    renderRoutes(routes, path)

    expect(page()).toHaveTextContent(expected)
  })

  it('say so at an unknown address, under the navbar', () => {
    renderRoutes(routes, '/no-such-page')

    expect(within(page()).getByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(navbar()).toBeInTheDocument()
  })

  it('show an error page in place of a page that crashes, keeping the navbar', () => {
    // React and the router log the error; keep the test output clean
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.mocked(HomePage).mockImplementation(() => { throw new Error('Broken page') })

    renderRoutes(routes, '/')

    expect(within(page()).getByRole('heading', { name: 'Something went wrong' })).toBeInTheDocument()
    expect(navbar()).toBeInTheDocument()
  })

  // The focused control goes with the page, and the path is unchanged, so
  // only the error page itself can take focus off <body>
  it("focus the error page's heading when a page crashes after showing", async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.mocked(HomePage).mockImplementation(BreaksOnClick)
    const { user } = renderRoutes(routes, '/')

    await user.click(screen.getByRole('button', { name: 'Break' }))

    expect(within(page()).getByRole('heading', { name: 'Something went wrong' })).toHaveFocus()
  })

  it('show the error page inside a main landmark when the layout itself crashes', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.mocked(Navbar).mockImplementation(() => { throw new Error('Broken navbar') })

    renderRoutes(routes, '/')

    expect(within(page()).getByRole('heading', { name: 'Something went wrong' })).toBeInTheDocument()
    expect(navbar()).not.toBeInTheDocument()
  })
})
