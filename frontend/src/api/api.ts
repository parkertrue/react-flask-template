import axios from 'axios'
import { storage } from '@/auth/storage'
import type { Tokens } from '@/auth/authService'
import { errorCode, errorResponse } from './errors'

declare module 'axios' {
  interface InternalAxiosRequestConfig {
    // Set on a request retried after a refresh, so it is retried only once
    _retry?: boolean
  }
}

// Same-origin in every environment, so the refresh cookie goes along
// without withCredentials
export const api = axios.create({
  baseURL: '/api'
})

// Endpoints authenticated by the refresh cookie, which the backend protects
// with a double-submit CSRF header. '/auth/logout' also covers '/auth/logout-all'.
const REFRESH_COOKIE_ENDPOINTS = ['/auth/refresh', '/auth/logout']

// Tabs share the refresh cookie, and each refresh revokes the token it
// used, so two tabs refreshing at once would sign the slower one out. A Web
// Lock makes tabs take turns; one that waited finds the access token the
// other stored (localStorage is shared too) and uses it instead of
// refreshing again. Browsers without the API (or a non-HTTPS origin other
// than localhost) refresh without the lock.
async function refreshTokens(staleToken: string): Promise<string> {
  const refresh = async () => {
    const current = storage.getAccessToken()
    if (current && current !== staleToken) {
      return current
    }

    const response = await api.post<Tokens>('/auth/refresh')
    const { access_token, refresh_csrf } = response.data
    storage.setAccessToken(access_token)
    // Every refresh token carries its own CSRF value. Keeping the old one
    // makes the next refresh, and logout, fail the backend's CSRF check.
    storage.setRefreshCsrf(refresh_csrf)
    return access_token
  }

  // The DOM types say every browser has it; an insecure origin does not
  const locks = navigator.locks as LockManager | undefined
  return locks
    ? locks.request('auth-refresh', refresh)
    : refresh()
}

// Only one refresh may be in flight: requests that expire meanwhile share its
// promise, so they retry with the token it produces or fail with its error.
let refreshing: Promise<string> | null = null

function sharedRefresh(staleToken: string) {
  refreshing ??= refreshTokens(staleToken)
    .catch((refreshError: unknown) => {
      // Only a 401 means the session is over. A 429, a 503 or a network
      // error is temporary: keep the session, fail just these requests with
      // the refresh's own message, and let the next request try again.
      // Clearing storage ends the session everywhere: AuthProvider re-renders
      // and ProtectedRoute sends the user to log in, without a page reload,
      // where the login page says the session has ended.
      if (errorResponse(refreshError)?.status === 401) {
        storage.endSession()
      }
      throw refreshError
    })
    .finally(() => {
      refreshing = null
    })
  return refreshing
}

api.interceptors.request.use(config => {
  const token = storage.getAccessToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }

  if (REFRESH_COOKIE_ENDPOINTS.some(endpoint => config.url?.startsWith(endpoint))) {
    const csrf = storage.getRefreshCsrf()
    if (csrf) {
      config.headers['X-CSRF-REFRESH-TOKEN'] = csrf
    }
  }

  return config
})

api.interceptors.response.use(
  response => response,
  async (error: unknown) => {
    // No config: the request never went out, since a request interceptor
    // threw (storage blocked by the browser, say). Nothing to retry.
    if (!axios.isAxiosError(error) || !error.config) {
      throw error
    }
    const originalRequest = error.config

    const code = errorCode(error)
    const url = originalRequest.url
    const authorization = originalRequest.headers.Authorization

    // Only refresh when an authenticated request failed on an expired token
    if (
      code === 'AUTH_TOKEN_EXPIRED' &&
      typeof authorization === 'string' &&
      !url?.startsWith('/auth/') &&
      !originalRequest._retry
    ) {
      originalRequest._retry = true
      const staleToken = authorization.replace(/^Bearer /, '')
      const access_token = await sharedRefresh(staleToken)
      originalRequest.headers.Authorization = `Bearer ${access_token}`
      return api(originalRequest)
    }

    if (
      (code === 'AUTH_INVALID_TOKEN' || code === 'AUTH_MISSING_TOKEN') &&
      !url?.startsWith('/auth/logout')
    ) {
      storage.endSession()
    }

    throw error
  }
)
