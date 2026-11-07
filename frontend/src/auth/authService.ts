import { api } from '@/api/api'

// The body of a successful login or refresh. No refresh_csrf when the
// backend's CSRF check is off (IntegrationConfig's headless API tests).
export interface Tokens {
  access_token: string
  refresh_csrf?: string
}

// The body of GET /api/account; created_at is an ISO 8601 time in UTC
export interface Account {
  email: string
  created_at: string
}

// termsVersion: the version of the terms the user was shown and accepted
export async function registerUser(email: string, password: string, termsVersion: number) {
  await api.post('/auth/register', { email, password, terms_version: termsVersion })
}

export async function loginUser(email: string, password: string) {
  const response = await api.post<Tokens>('/auth/login', { email, password })
  return response.data
}

export async function getAccount() {
  const response = await api.get<Account>('/account')
  return response.data
}

// The password is asked for again, so an open session alone cannot delete
// the account
export async function deleteAccount(password: string) {
  await api.post('/account/delete', { password })
}

export async function logoutUser() {
  await api.post('/auth/logout')
}

export async function logoutAllDevices() {
  await api.post('/auth/logout-all')
}

// For when logging out failed: the refresh cookie is HttpOnly, so only the
// server can expire it. If this fails too, there is nothing more the client
// can do, so it never throws. The JSON body is required: it stops other sites
// calling this without CORS.
export async function clearAuthCookies() {
  await api.post('/auth/clear-cookies', {}).catch(() => {})
}
