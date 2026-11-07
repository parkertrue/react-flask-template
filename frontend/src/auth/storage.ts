const KEYS = {
  ACCESS_TOKEN: 'access_token',
  REFRESH_CSRF: 'refresh_csrf',
  EMAIL: 'email',
  // Set when a session ends on its own rather than by logout
  SESSION_ENDED: 'session_ended'
}

const listeners = new Set<() => void>()
const notify = () => listeners.forEach(listener => listener())

const removeAll = () => Object.values(KEYS).forEach(key => localStorage.removeItem(key))

// No value removes the key: a refresh token without a CSRF value (the
// backend sends none when its CSRF check is off) leaves none behind
const setOrRemoveItem = (key: string, value: string | null | undefined) => {
  if (value) {
    localStorage.setItem(key, value)
  } else {
    localStorage.removeItem(key)
  }
  notify()
}

// Access tokens are stored in localStorage (XSS-accessible). This is an accepted
// risk mitigated by: short 15-min expiry, HttpOnly refresh cookie, CSP headers,
// and React's output escaping. The refresh token itself is HttpOnly-only.
export const storage = {
  getAccessToken: () => localStorage.getItem(KEYS.ACCESS_TOKEN),
  setAccessToken: (token: string | null) => setOrRemoveItem(KEYS.ACCESS_TOKEN, token),

  getRefreshCsrf: () => localStorage.getItem(KEYS.REFRESH_CSRF),
  setRefreshCsrf: (csrf: string | null | undefined) => setOrRemoveItem(KEYS.REFRESH_CSRF, csrf),

  getEmail: () => localStorage.getItem(KEYS.EMAIL),
  setEmail: (email: string | null) => setOrRemoveItem(KEYS.EMAIL, email),

  // A session that ended on purpose: logout
  clearAuth: () => {
    removeAll()
    notify()
  },

  // A session that ended on its own (its time ran out, or another device
  // logged out everywhere), so the login page can say why the user is there.
  // The flag lasts until the next login or logout.
  endSession: () => {
    removeAll()
    localStorage.setItem(KEYS.SESSION_ENDED, 'true')
    notify()
  },
  getSessionEnded: () => localStorage.getItem(KEYS.SESSION_ENDED) === 'true',
  clearSessionEnded: () => setOrRemoveItem(KEYS.SESSION_ENDED, null),

  // For useSyncExternalStore: calls the listener whenever the session changes,
  // here or in another tab (the browser's storage event covers those)
  subscribe: (listener: () => void) => {
    listeners.add(listener)
    window.addEventListener('storage', listener)
    return () => {
      listeners.delete(listener)
      window.removeEventListener('storage', listener)
    }
  }
}
