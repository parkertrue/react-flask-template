import { useEffect, useRef, useState, type SubmitEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@/auth/useAuth'
import { useLogout } from '@/auth/useLogout'
import {
  getAccount, logoutAllDevices, clearAuthCookies, deleteAccount, exportAccountData,
  requestEmailChange, changePassword, EMAIL_CHANGE_LINK_HOURS,
} from '@/auth/authService'
import { errorCode, errorResponse, getErrorMessage } from '@/api/errors'
import ConfirmDialog from '@/components/dialogs/ConfirmDialog'
import FormDialog from '@/components/dialogs/FormDialog'
import FormField from '@/components/forms/FormField'
import { useFormFields } from '@/components/forms/useFormFields'
import PageTitle from '@/components/layout/PageTitle'
import { saveJsonFile, slugify } from '@/utils/download'
import {
  validateEmail, validateNotGuessable, validatePassword, validatePasswordMatch,
  EMAIL_MAX_LENGTH, PASSWORD_INPUT_MAX_LENGTH, PASSWORD_MIN_LENGTH,
} from '@/utils/validation'
import { hours } from '@/utils/time'
import { APP_NAME } from '@/appInfo'
import { ACCOUNT_QUERY_KEY } from './accountQuery'
import type { LoginState } from './LoginPage'
import SessionList from './SessionList'

// The export's file name starts with the app's name
const EXPORT_FILE_PREFIX = slugify(APP_NAME)

export default function AccountPage() {
  const { email, login, updateEmail } = useAuth()
  const logOut = useLogout()
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [askingLogoutAll, setAskingLogoutAll] = useState(false)
  const logoutAllButton = useRef<HTMLButtonElement>(null)
  // Refetched when the window regains focus: an email change completes in
  // the tab its link opens, or on another device (DECISIONS.md, caching)
  const { data: account, error: accountError } = useQuery({
    queryKey: ACCOUNT_QUERY_KEY, queryFn: getAccount, refetchOnWindowFocus: true,
  })
  const emailChange = useFormFields({ 'new-email': '', 'email-password': '' })
  const [askingEmail, setAskingEmail] = useState(false)
  const [changingEmail, setChangingEmail] = useState(false)
  const [emailError, setEmailError] = useState<string | null>(null)
  // Where the link went, on the persistent status line
  const [emailStatus, setEmailStatus] = useState('')
  const passwordChange = useFormFields({ 'current-password': '', 'new-password': '', 'confirm-new-password': '' })
  const [askingPassword, setAskingPassword] = useState(false)
  const [changingPassword, setChangingPassword] = useState(false)
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [passwordStatus, setPasswordStatus] = useState('')
  const loadError = accountError && getErrorMessage(accountError)
  const deletion = useFormFields({ 'delete-password': '' })
  const [askingDelete, setAskingDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)
  // Cleared when the next export starts, so the same words are read again
  const [exportStatus, setExportStatus] = useState('')

  // The account's address changed elsewhere (its link opened in another
  // tab or on another device): show the new one everywhere, the navbar too
  const accountEmail = account?.email
  useEffect(() => {
    if (accountEmail) updateEmail(accountEmail)
  }, [accountEmail, updateEmail])

  // Each time afresh: no address, password or message from an earlier try
  const askToChangeEmail = () => {
    emailChange.reset()
    setEmailError(null)
    setAskingEmail(true)
  }

  const handleEmailChange = async (e: SubmitEvent<HTMLFormElement>) => {
    const form = e.currentTarget
    const { values } = emailChange
    const valid = emailChange.validate(form, {
      'new-email': validateEmail(values['new-email']),
      'email-password': validatePassword(values['email-password']),
    })
    if (!valid) return
    setEmailError(null)
    setEmailStatus('')
    setChangingEmail(true)
    try {
      await requestEmailChange(values['new-email'], values['email-password'])
    } catch (err) {
      // Nothing was sent: the dialog stays for another try
      setChangingEmail(false)
      const code = errorCode(err)
      if (code === 'WRONG_PASSWORD') {
        emailChange.validate(form, { 'email-password': getErrorMessage(err) })
      } else if (code === 'EMAIL_UNCHANGED') {
        emailChange.validate(form, { 'new-email': getErrorMessage(err) })
      } else {
        setEmailError(getErrorMessage(err))
      }
      return
    }
    setChangingEmail(false)
    setAskingEmail(false)
    setEmailStatus(
      `We sent a link to ${values['new-email']}. Open it within ${hours(EMAIL_CHANGE_LINK_HOURS)} to move your account there.`)
  }

  // Each time afresh: no passwords or message from an earlier try
  const askToChangePassword = () => {
    passwordChange.reset()
    setPasswordError(null)
    setAskingPassword(true)
  }

  const handlePasswordChange = async (e: SubmitEvent<HTMLFormElement>) => {
    const form = e.currentTarget
    const { values } = passwordChange
    const current = values['current-password']
    const next = values['new-password']
    const valid = passwordChange.validate(form, {
      'current-password': validatePassword(current),
      'new-password': validatePassword(next) ?? validateNotGuessable(next, email ?? '')
        ?? (next === current ? 'Choose a password different from your current one.' : undefined),
      'confirm-new-password': validatePasswordMatch(next, values['confirm-new-password']),
    })
    if (!valid || !email) return
    setPasswordError(null)
    setPasswordStatus('')
    setChangingPassword(true)
    try {
      const tokens = await changePassword(current, next)
      // Every device was logged out, this one too: this is its new login
      login(tokens.access_token, tokens.refresh_csrf, email)
    } catch (err) {
      // Nothing changed: the dialog stays for another try
      setChangingPassword(false)
      const code = errorCode(err)
      if (code === 'WRONG_PASSWORD') {
        passwordChange.validate(form, { 'current-password': getErrorMessage(err) })
      } else if (code === 'PASSWORD_UNCHANGED' || code === 'PASSWORD_GUESSABLE' || code === 'PASSWORD_BREACHED') {
        passwordChange.validate(form, { 'new-password': getErrorMessage(err) })
      } else {
        setPasswordError(getErrorMessage(err))
      }
      return
    }
    setChangingPassword(false)
    setAskingPassword(false)
    setPasswordStatus('Your password was changed. Every other device was logged out.')
  }

  // Not while a request is in flight: its button is busy
  const askToLogoutAll = () => {
    if (!submitting) setAskingLogoutAll(true)
  }

  const handleLogoutAll = async () => {
    setAskingLogoutAll(false)
    setError(null)
    setSubmitting(true)
    try {
      await logoutAllDevices()
    } catch (err) {
      // Signing out other devices happens only on the server, so if that
      // failed they are all still signed in: say so, and keep this session
      // for a retry. A 401 means this session has ended anyway.
      if (errorResponse(err)?.status !== 401) {
        setError(getErrorMessage(err))
        setSubmitting(false)
        return
      }
      await clearAuthCookies()
    }
    await logOut()
  }

  // Fetched, then saved from memory: the request needs the access token, so
  // the browser cannot download it from a plain link
  const handleExport = async () => {
    if (exporting) return
    setExportError(null)
    setExportStatus('')
    setExporting(true)
    try {
      const data = await exportAccountData()
      // Dated by the server's clock, in UTC, like the export's own timestamp
      const filename = `${EXPORT_FILE_PREFIX}-data-${data.exported_at.slice(0, 10)}.json`
      saveJsonFile(filename, data)
      setExportStatus(`Download started: ${filename}`)
    } catch (err) {
      setExportError(getErrorMessage(err))
    } finally {
      setExporting(false)
    }
  }

  // Each time afresh: no password or message from an earlier try
  const askToDelete = () => {
    deletion.reset()
    setDeleteError(null)
    setAskingDelete(true)
  }

  // Typing the password in the dialog is the confirmation
  const handleDelete = async (e: SubmitEvent<HTMLFormElement>) => {
    const form = e.currentTarget
    const valid = deletion.validate(form, {
      'delete-password': validatePassword(deletion.values['delete-password']),
    })
    if (!valid) return
    setDeleteError(null)
    setDeleting(true)
    try {
      await deleteAccount(deletion.values['delete-password'])
    } catch (err) {
      // Nothing was deleted: a wrong password, or the server could not end
      // the account's sessions. The dialog stays for another try. A session
      // that has ended takes the user to the login page on its own.
      setDeleting(false)
      if (errorCode(err) === 'WRONG_PASSWORD') {
        // The field's own message, focused, like a failed submit's
        deletion.validate(form, { 'delete-password': getErrorMessage(err) })
      } else {
        setDeleteError(getErrorMessage(err))
      }
      return
    }
    // Then the login page, which says the account is gone; a signed-in user
    // would be sent on from there
    await logOut()
    const state: LoginState = { accountDeleted: true }
    await navigate('/login', { replace: true, state })
  }

  return (
    <div className="account-page page-column">
      <PageTitle>Account</PageTitle>
      <h1>Account</h1>
      <p>Signed in as <strong>{email}</strong></p>
      {/* One persistent live region, so the loaded details are announced */}
      <p role="status">
        {account && (
          <>
            Member since{' '}
            <time dateTime={account.created_at}>
              {new Date(account.created_at).toLocaleDateString(undefined, { dateStyle: 'long' })}
            </time>
          </>
        )}
        {!account && !loadError && 'Loading account details...'}
      </p>
      {loadError && <div className="error-message" role="alert">{loadError}</div>}

      <section aria-labelledby="email-heading">
        <h2 id="email-heading">Email</h2>
        <p>Move this account to another email address. We'll email the new address a link to confirm it.</p>
        <button type="button" onClick={askToChangeEmail} className="btn btn-secondary">
          Change email
        </button>
        {/* In the page from the start, so it is announced; boxed once it
            says something, so it is seen */}
        <p role="status" className={emailStatus ? 'success-message' : undefined}>{emailStatus}</p>
        {askingEmail && (
          <FormDialog
            title="Change your email?"
            description="Nothing changes until you open the link we email the new address."
            submitLabel={changingEmail ? 'Sending link...' : 'Send link'}
            busy={changingEmail}
            onSubmit={e => void handleEmailChange(e)}
            onCancel={() => setAskingEmail(false)}
          >
            <FormField
              id="new-email"
              label="New email"
              type="email"
              autoComplete="email"
              value={emailChange.values['new-email']}
              onChange={emailChange.handleChange}
              error={emailChange.errors['new-email']}
              readOnly={changingEmail}
              required
              maxLength={EMAIL_MAX_LENGTH}
            />
            <FormField
              id="email-password"
              label="Password"
              hint="Enter your password to confirm."
              type="password"
              autoComplete="current-password"
              value={emailChange.values['email-password']}
              onChange={emailChange.handleChange}
              error={emailChange.errors['email-password']}
              readOnly={changingEmail}
              required
              maxLength={PASSWORD_INPUT_MAX_LENGTH}
            />
            {emailError && <div className="error-message" role="alert">{emailError}</div>}
          </FormDialog>
        )}
      </section>

      <section aria-labelledby="password-heading">
        <h2 id="password-heading">Password</h2>
        <p>Change the password you log in with. Every other device will be logged out.</p>
        <button type="button" onClick={askToChangePassword} className="btn btn-secondary">
          Change password
        </button>
        <p role="status" className={passwordStatus ? 'success-message' : undefined}>{passwordStatus}</p>
        {askingPassword && (
          <FormDialog
            title="Change your password?"
            description="Every other device signed in to this account will be logged out."
            submitLabel={changingPassword ? 'Saving...' : 'Save password'}
            busy={changingPassword}
            onSubmit={e => void handlePasswordChange(e)}
            onCancel={() => setAskingPassword(false)}
          >
            {/* The account's name, for password managers to update */}
            <FormField
              id="password-username"
              label="Email"
              type="email"
              autoComplete="username"
              value={email ?? ''}
              readOnly
            />
            <FormField
              id="current-password"
              label="Current password"
              type="password"
              autoComplete="current-password"
              value={passwordChange.values['current-password']}
              onChange={passwordChange.handleChange}
              error={passwordChange.errors['current-password']}
              readOnly={changingPassword}
              required
              maxLength={PASSWORD_INPUT_MAX_LENGTH}
            />
            <FormField
              id="new-password"
              label="New password"
              type="password"
              autoComplete="new-password"
              value={passwordChange.values['new-password']}
              onChange={passwordChange.handleChange}
              error={passwordChange.errors['new-password']}
              hint={`At least ${PASSWORD_MIN_LENGTH} characters.`}
              readOnly={changingPassword}
              required
              maxLength={PASSWORD_INPUT_MAX_LENGTH}
            />
            <FormField
              id="confirm-new-password"
              label="Confirm new password"
              type="password"
              autoComplete="new-password"
              value={passwordChange.values['confirm-new-password']}
              onChange={passwordChange.handleChange}
              error={passwordChange.errors['confirm-new-password']}
              readOnly={changingPassword}
              required
              maxLength={PASSWORD_INPUT_MAX_LENGTH}
            />
            {passwordError && <div className="error-message" role="alert">{passwordError}</div>}
          </FormDialog>
        )}
      </section>

      <section aria-labelledby="sessions-heading">
        <h2 id="sessions-heading">Sessions</h2>
        <p>Where this account is signed in. Log out a device you don't recognise, then change your password.</p>
        <SessionList fallbackFocus={() => logoutAllButton.current?.focus()} />
        <p>Or log out everywhere this account is signed in, including this browser.</p>
        {error && <div className="error-message" role="alert">{error}</div>}
        <button
          type="button"
          ref={logoutAllButton}
          onClick={askToLogoutAll}
          aria-disabled={submitting}
          className="btn btn-danger"
        >
          {submitting ? 'Logging out...' : 'Log out all devices'}
        </button>
        {askingLogoutAll && (
          <ConfirmDialog
            title="Log out all devices?"
            confirmLabel="Log out all devices"
            onConfirm={() => void handleLogoutAll()}
            onCancel={() => setAskingLogoutAll(false)}
          >
            <p>
              Every device signed in to this account, this browser included,
              will have to log in again.
            </p>
          </ConfirmDialog>
        )}
      </section>

      <section aria-labelledby="data-heading">
        <h2 id="data-heading">Your data</h2>
        <p>Download a copy of everything this account holds, as a JSON file.</p>
        {exportError && <div className="error-message" role="alert">{exportError}</div>}
        <button
          type="button"
          onClick={() => void handleExport()}
          aria-disabled={exporting}
          className="btn btn-secondary"
        >
          {exporting ? 'Preparing download...' : 'Download your data'}
        </button>
        <p className="visually-hidden" role="status">{exportStatus}</p>
      </section>

      <section aria-labelledby="delete-heading">
        <h2 id="delete-heading">Delete account</h2>
        <p>Delete this account and everything in it. This cannot be undone.</p>
        <button type="button" onClick={askToDelete} className="btn btn-danger">
          Delete account
        </button>
        {askingDelete && (
          <FormDialog
            title="Delete your account?"
            description="Your account and everything in it will be deleted. This cannot be undone."
            submitLabel={deleting ? 'Deleting...' : 'Delete account'}
            busy={deleting}
            danger
            onSubmit={e => void handleDelete(e)}
            onCancel={() => setAskingDelete(false)}
          >
            <FormField
              id="delete-password"
              label="Password"
              hint="Enter your password to confirm."
              type="password"
              autoComplete="current-password"
              value={deletion.values['delete-password']}
              onChange={deletion.handleChange}
              error={deletion.errors['delete-password']}
              readOnly={deleting}
              required
              maxLength={PASSWORD_INPUT_MAX_LENGTH}
            />
            {deleteError && <div className="error-message" role="alert">{deleteError}</div>}
          </FormDialog>
        )}
      </section>
    </div>
  )
}
