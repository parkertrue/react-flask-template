import { Navigate, Outlet, useLocation, type Location } from 'react-router-dom'
import { useAuth } from './useAuth'

// Where logging in leads, unless ProtectedRoute sent the user from elsewhere
export const AFTER_LOGIN_PATH = '/notes'

// What ProtectedRoute leaves in the location's state
export interface FromState {
  from?: Location
}

// The parent route of the login and register pages, which a signed-in user
// has no use for. Logging in re-renders it, which is what moves the user on.
export default function GuestRoute() {
  const { isAuthenticated } = useAuth()
  const location = useLocation() as Location<FromState | null>

  if (isAuthenticated) {
    return <Navigate to={location.state?.from ?? AFTER_LOGIN_PATH} replace />
  }

  return <Outlet />
}
