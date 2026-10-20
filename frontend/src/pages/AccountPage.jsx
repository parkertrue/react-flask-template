import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/auth/useAuth'
import { useLogout } from '@/auth/useLogout'
import { getAccount, logoutAllDevices, clearAuthCookies, deleteAccount } from '@/auth/authService'
import { getErrorMessage } from '@/api/errors'
import ConfirmDialog from '@/components/dialogs/ConfirmDialog'
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
  const deletionForm = useRef(null)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
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

  // The password is checked here first, then the dialog asks once more
  const handleDeleteSubmit = (e) => {
    e.preventDefault()
    if (deleting) return
    const valid = deletion.validate(e.currentTarget, {
      'delete-password': validatePassword(deletion.values['delete-password']),
    })
    if (valid) setConfirmingDelete(true)
  }

  const handleDelete = async () => {
    setConfirmingDelete(false)
    setDeleteError(null)
    setDeleting(true)
    try {
      await deleteAccount(deletion.values['delete-password'])
    } catch (err) {
      // Nothing was deleted: a wrong password, or the server could not end
      // the account's sessions. A session that has ended takes the user to
      // the login page on its own.
      setDeleting(false)
      if (err.response?.data?.error?.code === 'WRONG_PASSWORD') {
        // The field's own message, focused, like a failed submit's
        deletion.validate(deletionForm.current, { 'delete-password': getErrorMessage(err) })
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
        <form
          ref={deletionForm}
          onSubmit={handleDeleteSubmit}
          noValidate
          aria-labelledby="delete-heading"
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
          <button type="submit" aria-disabled={deleting} className="btn btn-danger">
            {deleting ? 'Deleting...' : 'Delete account'}
          </button>
        </form>
        {confirmingDelete && (
          <ConfirmDialog
            title="Delete your account?"
            confirmLabel="Delete account"
            onConfirm={handleDelete}
            onCancel={() => setConfirmingDelete(false)}
          >
            <p>Your account and everything in it will be deleted. This cannot be undone.</p>
          </ConfirmDialog>
        )}
      </section>
    </div>
  )
}
