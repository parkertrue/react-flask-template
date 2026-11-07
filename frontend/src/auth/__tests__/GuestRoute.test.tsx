import { describe, it, expect } from 'vitest'
import { act, screen } from '@testing-library/react'
import GuestRoute, { AFTER_LOGIN_PATH } from '../GuestRoute'
import ProtectedRoute from '../ProtectedRoute'
import { renderRoutes, signIn } from '@/test/router'

const routes = [
  {
    element: <GuestRoute />,
    children: [{ path: '/login', element: <p>Login page</p> }],
  },
  {
    element: <ProtectedRoute />,
    children: [
      { path: AFTER_LOGIN_PATH, element: <p>After-login page</p> },
      { path: '/somewhere-else', element: <p>Another page</p> },
    ],
  },
]

describe('GuestRoute', () => {
  it('shows a visitor the page', () => {
    renderRoutes(routes, '/login')

    expect(screen.getByText('Login page')).toBeInTheDocument()
  })

  it('sends a signed-in user to the after-login page', () => {
    signIn()
    renderRoutes(routes, '/login')

    expect(screen.getByText('After-login page')).toBeInTheDocument()
  })

  it('moves the user on as soon as they log in', () => {
    renderRoutes(routes, '/login')

    act(() => signIn())

    expect(screen.getByText('After-login page')).toBeInTheDocument()
  })

  it('returns the user to the page that sent them to log in', () => {
    renderRoutes(routes, '/somewhere-else')
    expect(screen.getByText('Login page')).toBeInTheDocument()

    act(() => signIn())

    expect(screen.getByText('Another page')).toBeInTheDocument()
  })
})
