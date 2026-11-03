import { useState } from 'react'
import { useLogout } from './useLogout'
import { logoutUser, clearAuthCookies } from './authService'

export default function LogoutButton() {
  const logOut = useLogout()
  const [submitting, setSubmitting] = useState(false)

  // This device's session ends even if the server cannot be reached. Either
  // way the button goes with the session, so it never needs to be un-busied.
  const handleLogout = async () => {
    if (submitting) return
    setSubmitting(true)
    try {
      await logoutUser()
    } catch {
      await clearAuthCookies()
    }
    await logOut()
  }

  return (
    <button
      type="button"
      onClick={handleLogout}
      aria-disabled={submitting}
      className="btn btn-secondary btn-small"
    >
      {submitting ? 'Logging out...' : 'Log out'}
    </button>
  )
}
