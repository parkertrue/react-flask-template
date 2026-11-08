import { createContext } from 'react'

export interface AuthContextValue {
  email: string | null
  isAuthenticated: boolean
  // The last session ended on its own (it ran out, or was revoked)
  sessionEnded: boolean
  // csrf: the refresh token's CSRF value, when the backend sent one
  login: (accessToken: string, csrf: string | null | undefined, userEmail: string) => void
  logout: () => void
}

// Kept apart from AuthProvider: Vite's fast refresh only works on files that
// export nothing but components.
export const AuthContext = createContext<AuthContextValue | null>(null)
