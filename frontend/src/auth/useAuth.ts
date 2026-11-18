import { createContext, use } from 'react'

export interface AuthContextValue {
  email: string | null
  isAuthenticated: boolean
  // The last session ended on its own (it ran out, or was revoked)
  sessionEnded: boolean
  // csrf: the refresh token's CSRF value, when the backend sent one
  login: (accessToken: string, csrf: string | null | undefined, userEmail: string) => void
  logout: () => void
  // The signed-in account's own address changed (an email change): shown
  // at once, without emptying the cache, since the account is the same
  updateEmail: (newEmail: string) => void
}

// Kept apart from AuthProvider: Vite's fast refresh only works on files that
// export nothing but components.
export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth() {
  const context = use(AuthContext)

  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }

  return context
}
