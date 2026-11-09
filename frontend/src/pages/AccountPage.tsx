import { useState, type SubmitEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useAuth } from '@/auth/useAuth'
import { useLogout } from '@/auth/useLogout'
import {
  getAccount, logoutAllDevices, clearAuthCookies, deleteAccount, exportAccountData,
} from '@/auth/authService'
import { errorCode, errorResponse, getErrorMessage } from '@/api/errors'
import ConfirmDialog from '@/components/dialogs/ConfirmDialog'
import FormDialog from '@/components/dialogs/FormDialog'
import FormField from '@/components/forms/FormField'
import { useFormFields } from '@/components/forms/useFormFields'
import PageTitle from '@/components/layout/PageTitle'
import { saveJsonFile, slugify } from '@/utils/download'
import { validatePassword, PASSWORD_INPUT_MAX_LENGTH } from '@/utils/validation'
import { APP_NAME } from '@/appName'
import type { LoginState } from './LoginPage'

// The export's file name starts with the app's name
const EXPORT_FILE_PREFIX = slugify(APP_NAME)

export default function AccountPage() {
  const { email } = useAuth()
  const logOut = useLogout()
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [askingLogoutAll, setAskingLogoutAll] = useState(false)
  const { data: account, error: accountError } = useQuery({ queryKey: ['account'], queryFn: getAccount })
  const loadError = accountError && getErrorMessage(accountError)
  const deletion = useFormFields({ 'delete-password': '' })
  const [askingDelete, setAskingDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)
  // Cleared when the next export starts, so the same words are read again
  const [exportStatus, setExportStatus] = useState('')

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
      <p className="account-email">Signed in as <strong>{email}</strong></p>
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

      <section aria-labelledby="sessions-heading">
        <h2 id="sessions-heading">Sessions</h2>
        <p>Log out everywhere this account is signed in, including this browser.</p>
        {error && <div className="error-message" role="alert">{error}</div>}
        <button
          type="button"
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
