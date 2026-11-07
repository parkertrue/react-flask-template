import { useNavigate } from 'react-router-dom'
import { useAuth } from './useAuth'

// Ends this device's session on the home page. The session has to end after
// home is on screen, or a protected page still showing sends its
// ProtectedRoute to /login. A plain navigate is a transition, which
// logout()'s re-render would overtake; flushSync renders home now.
export function useLogout() {
  const { logout } = useAuth()
  const navigate = useNavigate()

  return async () => {
    await navigate('/', { flushSync: true })
    logout()
  }
}
