import { Link } from 'react-router-dom'
import EmailLinkRequest from '@/auth/EmailLinkRequest'
import { REGISTRATION_LINK_HOURS, requestRegistration } from '@/auth/authService'

// Sign-up's first step: the address to email a link to. The link's page,
// CompleteRegistrationPage, takes the password and makes the account. The
// backend answers alike whether the address has an account or not, so this
// page never says which.
export default function RegisterPage() {
  return (
    <EmailLinkRequest
      title="Sign up"
      hint="We'll email you a link to choose a password."
      submitLabel="Continue"
      busyLabel="Sending link..."
      send={requestRegistration}
      sentText={email => <>
        We sent a link to <strong>{email}</strong>. Open it within {REGISTRATION_LINK_HOURS} hours to
        choose a password and finish signing up.
      </>}
      note={
        <p className="form-note">
          How we use your address: see the{' '}
          <Link to="/privacy" className="text-link">Privacy notice</Link>.
        </p>
      }
      footer={
        <p className="auth-footer">
          Already have an account?{' '}
          <Link to="/login" className="text-link">Log in</Link>
        </p>
      }
    />
  )
}
