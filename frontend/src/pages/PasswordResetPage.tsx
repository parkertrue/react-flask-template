import { Link } from 'react-router-dom'
import EmailLinkRequest from '@/auth/EmailLinkRequest'
import { PASSWORD_RESET_LINK_HOURS, requestPasswordReset } from '@/auth/authService'

// A password reset's first step: the account's address, to email a link
// to. The link's page, CompletePasswordResetPage, takes the new password.
// The backend answers alike whether the address has an account or not, and
// emails only one that has, so this page never says which.
export default function PasswordResetPage() {
  return (
    <EmailLinkRequest
      title="Reset your password"
      hint="The one your account uses. We'll email it a link to choose a new password."
      submitLabel="Send link"
      busyLabel="Sending link..."
      send={requestPasswordReset}
      sentText={email => <>
        If <strong>{email}</strong> has an account, we sent it a link. Open it within{' '}
        {PASSWORD_RESET_LINK_HOURS * 60} minutes to choose a new password.
      </>}
      footer={
        <p className="auth-footer">
          Remembered it?{' '}
          <Link to="/login" className="text-link">Log in</Link>
        </p>
      }
    />
  )
}
