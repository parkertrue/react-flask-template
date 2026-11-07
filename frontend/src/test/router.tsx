import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider, type InitialEntry, type RouteObject } from 'react-router-dom'
import { AuthProvider } from '@/auth/AuthProvider'
import { storage } from '@/auth/storage'

/**
 * Render route objects (as in src/routes.tsx) at a path, inside the real
 * AuthProvider. `entry` is a path or a { pathname, state } location. Returns
 * the router, to read where it ended up, and a user-event instance.
 */
export function renderRoutes(routes: RouteObject[], entry: InitialEntry = '/') {
  const router = createMemoryRouter(routes, { initialEntries: [entry] })
  render(
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  )
  return { router, user: userEvent.setup() }
}

/** Store a session as logging in does; AuthProvider reads it from storage */
export function signIn(email = 'user@example.com') {
  storage.setEmail(email)
  storage.setRefreshCsrf('refresh-csrf')
  storage.setAccessToken('access-token')
}
