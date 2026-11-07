import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import LogoutButton from '../LogoutButton'
import ProtectedRoute from '../ProtectedRoute'
import { storage } from '../storage'
import { logoutUser, clearAuthCookies } from '../authService'
import { renderRoutes, signIn } from '@/test/router'

vi.mock('../authService')

// On a protected page, as in the app, where ending the session before home
// has rendered would send ProtectedRoute to /login instead
function renderButton() {
  signIn()
  return renderRoutes([
    { element: <ProtectedRoute />, children: [{ path: '/account', element: <LogoutButton /> }] },
    { path: '/', element: <p>Home page</p> },
    { path: '/login', element: <p>Login page</p> },
  ], '/account')
}

async function logOut({ user, router }: ReturnType<typeof renderButton>) {
  await user.click(screen.getByRole('button', { name: 'Log out' }))
  await screen.findByText('Home page')
  expect(router.state.location.pathname).toBe('/')
}

describe('LogoutButton', () => {
  beforeEach(() => {
    vi.mocked(logoutUser).mockResolvedValue()
    vi.mocked(clearAuthCookies).mockResolvedValue()
  })

  it('logs out on the server, ends the session and goes home', async () => {
    await logOut(renderButton())

    expect(logoutUser).toHaveBeenCalledTimes(1)
    expect(storage.getAccessToken()).toBeNull()
    // The logout response already expired the refresh cookie
    expect(clearAuthCookies).not.toHaveBeenCalled()
  })

  it('still ends the session if the server call fails, and clears the cookie', async () => {
    vi.mocked(logoutUser).mockRejectedValue(new Error('Network Error'))

    await logOut(renderButton())

    expect(storage.getAccessToken()).toBeNull()
    // HttpOnly: only the server can expire it
    expect(clearAuthCookies).toHaveBeenCalledTimes(1)
  })

  it('shows it is busy and logs out once however often it is clicked', async () => {
    const { promise, resolve: finish } = Promise.withResolvers<undefined>()
    vi.mocked(logoutUser).mockReturnValue(promise)
    const { user } = renderButton()

    await user.click(screen.getByRole('button', { name: 'Log out' }))
    const button = screen.getByRole('button', { name: 'Logging out...' })
    expect(button).toHaveAttribute('aria-disabled', 'true')
    await user.click(button)
    finish(undefined)
    await screen.findByText('Home page')

    expect(logoutUser).toHaveBeenCalledTimes(1)
  })
})
