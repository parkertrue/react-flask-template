import { describe, it, expect } from 'vitest'
import { act, screen } from '@testing-library/react'
import ProtectedRoute from '../ProtectedRoute'
import type { FromState } from '../GuestRoute'
import { storage } from '../storage'
import { renderRoutes, signIn } from '@/test/router'

const routes = [
  {
    element: <ProtectedRoute />,
    children: [{ path: '/private', element: <p>Private page</p> }],
  },
  { path: '/login', element: <p>Login page</p> },
]

describe('ProtectedRoute', () => {
  it('sends a visitor to the login page, remembering where they were going', () => {
    const { router } = renderRoutes(routes, '/private')

    expect(screen.getByText('Login page')).toBeInTheDocument()
    expect((router.state.location.state as FromState).from?.pathname).toBe('/private')
  })

  it('shows a signed-in user the page', () => {
    signIn()
    renderRoutes(routes, '/private')

    expect(screen.getByText('Private page')).toBeInTheDocument()
  })

  it('sends the user to log in when the session ends while on the page', () => {
    signIn()
    renderRoutes(routes, '/private')

    act(() => storage.clearAuth())

    expect(screen.getByText('Login page')).toBeInTheDocument()
  })
})
