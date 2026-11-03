import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/auth/useAuth'
import { useLogout } from '@/auth/useLogout'
import { getAccount, logoutAllDevices, clearAuthCookies, deleteAccount } from '@/auth/authService'
import { getErrorMessage } from '@/api/errors'
import FormDialog from '@/components/dialogs/FormDialog'
import FormField from '@/components/forms/FormField'
import { useFormFields } from '@/components/forms/useFormFields'
import PageTitle from '@/components/layout/PageTitle'
import { validatePassword, PASSWORD_MAX_LENGTH } from '@/utils/validation'

export default function AccountPage() {
  const { email } = useAuth()
  const logOut = useLogout()
  const navigate = useNavigate()
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [account, setAccount] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const deletion = useFormFields({ 'delete-password': '' })
  const [askingDelete, setAskingDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState(null)

  useEffect(() => {
    getAccount()
      .then(setAccount)
      .catch(err => setLoadError(getErrorMessage(err)))
  }, [])

  const handleLogoutAll = async () => {
    if (submitting) return
    setError(null)
    setSubmitting(true)
    try {
      await logoutAllDevices()
    } catch (err) {
      // Signing out other devices happens only on the server, so if that
      // failed they are all still signed in: say so, and keep this session
      // for a retry. A 401 means this session has ended anyway.
      if (err.response?.status !== 401) {
        setError(getErrorMessage(err))
        setSubmitting(false)
        return
      }
      await clearAuthCookies()
    }
    await logOut()
  }

  // Each time afresh: no password or message from an earlier try
  const askToDelete = () => {
    deletion.reset()
    setDeleteError(null)
    setAskingDelete(true)
  }

  // Typing the password in the dialog is the confirmation
  const handleDelete = async (e) => {
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
      if (err.response?.data?.error?.code === 'WRONG_PASSWORD') {
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
    await navigate('/login', { replace: true, state: { accountDeleted: true } })
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
          onClick={handleLogoutAll}
          aria-disabled={submitting}
          className="btn btn-danger"
        >
          {submitting ? 'Logging out...' : 'Log out all devices'}
        </button>
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
            onSubmit={handleDelete}
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
              maxLength={PASSWORD_MAX_LENGTH}
            />
            {deleteError && <div className="error-message" role="alert">{deleteError}</div>}
          </FormDialog>
        )}
      </section>
    </div>
  )
}
