import { api } from '@/api/api'
import type {
  AccountDeleteRequest, AccountResponse, DataExportResponse, EmailChangeRequest,
  EmailChangedResponse, EmailLinkRequest, LoginRequest, PasswordChangeRequest,
  PasswordResetCompleteRequest, PasswordResetRequest, RegisterCompleteRequest,
  RegisterCompleteResponse, RegisterRequest, TokensResponse,
} from '@/api/schemas'

// The body of a successful login or refresh. No refresh_csrf when the
// backend's CSRF check is off (IntegrationConfig's headless API tests).
export type Tokens = TokensResponse

// The body of a completed sign-up: the login's, and the account's address,
// the one its token named
export type RegistrationComplete = RegisterCompleteResponse

// The body of GET /api/account; created_at is an ISO 8601 time in UTC
export type Account = AccountResponse

// The body of GET /api/account/export: the account, and each feature's rows
// under its name
export type DataExport = DataExportResponse

// How long the emailed links work, mirroring REGISTRATION_LINK_HOURS and
// PASSWORD_RESET_LINK_HOURS in backend/app/auth/emails.py (a test keeps them
// in step)
export const REGISTRATION_LINK_HOURS = 24
export const PASSWORD_RESET_LINK_HOURS = 1
// And EMAIL_CHANGE_LINK_HOURS in backend/app/account/emails.py
export const EMAIL_CHANGE_LINK_HOURS = 24

// Sign-up's first step: emails the address a link to finish. Answered
// alike whether the address has an account or not.
export async function requestRegistration(email: string) {
  await api.post('/auth/register', { email } satisfies RegisterRequest)
}

// Sign-up's second step, with the emailed link's token: makes the account
// and logs in. termsVersion: the version of the terms the user was shown and
// accepted
export async function completeRegistration(token: string, password: string, termsVersion: number) {
  const response = await api.post<RegistrationComplete>(
    '/auth/register/complete',
    { token, password, terms_version: termsVersion } satisfies RegisterCompleteRequest)
  return response.data
}

// A password reset's first step: emails the account a link to choose a new
// password. Answered alike whether the address has an account or not.
export async function requestPasswordReset(email: string) {
  await api.post('/auth/password-reset', { email } satisfies PasswordResetRequest)
}

// A password reset's second step, with the emailed link's token. Ends every
// session of the account, this browser's too; signs in nowhere.
export async function completePasswordReset(token: string, password: string) {
  await api.post(
    '/auth/password-reset/complete', { token, password } satisfies PasswordResetCompleteRequest)
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

// An email change's first step: emails the new address a link that moves
// the account there. Answered alike whether the address has an account.
export async function requestEmailChange(email: string, password: string) {
  await api.post('/account/email', { email, password } satisfies EmailChangeRequest)
}

// The link to the new address: moves the account there; the answer is its
// address now
export async function completeEmailChange(token: string) {
  const response = await api.post<EmailChangedResponse>(
    '/account/email/complete', { token } satisfies EmailLinkRequest)
  return response.data
}

// The link to the old address: moves the account back and ends every session
export async function undoEmailChange(token: string) {
  const response = await api.post<EmailChangedResponse>(
    '/account/email/undo', { token } satisfies EmailLinkRequest)
  return response.data
}

// Replaces the password, given the current one. Every device is logged
// out, this one included: the answer is this device's new login.
export async function changePassword(currentPassword: string, newPassword: string) {
  const response = await api.post<Tokens>('/account/password', {
    current_password: currentPassword, new_password: newPassword,
  } satisfies PasswordChangeRequest)
  return response.data
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
