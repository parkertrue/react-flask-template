import { api } from '@/api/api'
import type {
  AccountDeleteRequest, AccountResponse, DataExportResponse, LoginRequest,
  RegisterCompleteRequest, RegisterRequest, TokensResponse,
} from '@/api/schemas'

// The body of a successful login or refresh. No refresh_csrf when the
// backend's CSRF check is off (IntegrationConfig's headless API tests).
export type Tokens = TokensResponse

// The body of GET /api/account; created_at is an ISO 8601 time in UTC
export type Account = AccountResponse

// The body of GET /api/account/export: the account, and each feature's rows
// under its name
export type DataExport = DataExportResponse

// Sign-up's first step: emails the address a link to finish. Answered
// alike whether the address has an account or not.
export async function requestRegistration(email: string) {
  await api.post('/auth/register', { email } satisfies RegisterRequest)
}

// Sign-up's second step, with the emailed link's token: makes the account
// and logs in. termsVersion: the version of the terms the user was shown and
// accepted
export async function completeRegistration(token: string, password: string, termsVersion: number) {
  const response = await api.post<Tokens>(
    '/auth/register/complete',
    { token, password, terms_version: termsVersion } satisfies RegisterCompleteRequest)
  return response.data
}

export async function loginUser(email: string, password: string) {
  const response = await api.post<Tokens>('/auth/login', { email, password } satisfies LoginRequest)
  return response.data
}

export async function getAccount() {
  const response = await api.get<Account>('/account')
  return response.data
}

export async function exportAccountData() {
  const response = await api.get<DataExport>('/account/export')
  return response.data
}

// The password is asked for again, so an open session alone cannot delete
// the account
export async function deleteAccount(password: string) {
  await api.post('/account/delete', { password } satisfies AccountDeleteRequest)
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
