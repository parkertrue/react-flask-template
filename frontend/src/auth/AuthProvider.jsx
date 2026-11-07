import { useEffect, useState, useSyncExternalStore } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { createQueryClient } from '@/api/queryClient'
import { storage } from './storage'
import { AuthContext } from './AuthContext'

export function AuthProvider({ children }) {
  // Storage holds the one copy of the session. The api client ends it there
  // when a refresh fails, and other tabs change it too; reading it straight
  // from storage, every component sees each change at once.
  const token = useSyncExternalStore(storage.subscribe, storage.getAccessToken)
  const email = useSyncExternalStore(storage.subscribe, storage.getEmail)
  const sessionEnded = useSyncExternalStore(storage.subscribe, storage.getSessionEnded)

  // The session owns the cache of server data
  const [queryClient] = useState(createQueryClient)

  // Empty the cache whenever the account changes: every way a session ends
  // (logout, a refused refresh, another tab) clears storage, and another
  // tab may sign in as someone else. It runs as storage changes, before
  // React renders, so no page ever shows the last account's data. Not on
  // the access token, which changes on every refresh.
  useEffect(() => {
    let account = storage.getEmail()
    return storage.subscribe(() => {
      const current = storage.getEmail()
      if (current === account) return
      account = current
      queryClient.clear()
    })
  }, [queryClient])

  const login = (accessToken, csrf, userEmail) => {
    storage.clearSessionEnded()
    storage.setEmail(userEmail)
    storage.setRefreshCsrf(csrf)
    storage.setAccessToken(accessToken)
  }

  const value = {
    email,
    isAuthenticated: !!token,
    sessionEnded,
    login,
    logout: storage.clearAuth
  }

  return (
    <AuthContext.Provider value={value}>
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    </AuthContext.Provider>
  )
}
