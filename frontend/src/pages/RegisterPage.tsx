import { useEffect, useRef, useState, type SubmitEvent } from 'react'
import { Link } from 'react-router-dom'
import { requestRegistration } from '@/auth/authService'
import { getErrorMessage } from '@/api/errors'
import FormField from '@/components/forms/FormField'
import { useFormFields } from '@/components/forms/useFormFields'
import PageTitle from '@/components/layout/PageTitle'
import { validateEmail, EMAIL_MAX_LENGTH } from '@/utils/validation'

// Sign-up's first step: the address to email a link to. The link's page,
// CompleteRegistrationPage, takes the password and makes the account. The
// backend answers alike whether the address has an account or not, so this
// page never says which.
export default function RegisterPage() {
  const { values, errors, handleChange, validate } = useFormFields({ email: '' })
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  // The address the link went to, once it has
  const [sentTo, setSentTo] = useState<string | null>(null)
  // "Sent again", announced on the persistent status line
  const [status, setStatus] = useState('')
  const heading = useRef<HTMLHeadingElement>(null)
  const shownStep = useRef(sentTo)

  // The step changes without a navigation, so focus moves by hand to the
  // heading that names it, as Layout's does on a new page
  useEffect(() => {
    if (shownStep.current === sentTo) return
    shownStep.current = sentTo
    heading.current?.focus()
  }, [sentTo])

  const send = async (email: string) => {
    setFormError(null)
    setStatus('')
    setSubmitting(true)
    try {
      await requestRegistration(email)
      return true
    } catch (err) {
      setFormError(getErrorMessage(err))
      return false
    } finally {
      setSubmitting(false)
    }
  }

  const handleSubmit = async (e: SubmitEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (submitting) return
    if (!validate(e.currentTarget, { email: validateEmail(values.email) })) return

    if (await send(values.email)) setSentTo(values.email)
  }

  const handleSendAgain = async () => {
    if (submitting || sentTo === null) return
    if (await send(sentTo)) setStatus(`Sent again to ${sentTo}.`)
  }

  const handleUseAnother = () => {
    if (submitting) return
    setFormError(null)
    setStatus('')
    setSentTo(null)
  }

  const error = formError && <div className="error-message" role="alert">{formError}</div>

  if (sentTo !== null) {
    return (
      <div className="centered-page">
        <PageTitle>Check your inbox</PageTitle>
        <div className="auth-container">
          <div className="auth-card">
            <h1 ref={heading} tabIndex={-1}>Check your inbox</h1>
            <p className="sent-to">
              We sent a link to <strong>{sentTo}</strong>. Open it within 24 hours to
              choose a password and finish signing up.
            </p>
            <p>Not there? Check your spam folder, or send it again.</p>
            {error}
            <p className="visually-hidden" role="status">{status}</p>
            <div className="auth-actions">
              <button
                type="button"
                onClick={() => void handleSendAgain()}
                aria-disabled={submitting}
                className="btn btn-primary"
              >
                {submitting ? 'Sending...' : 'Send again'}
              </button>
              <button
                type="button"
                onClick={handleUseAnother}
                aria-disabled={submitting}
                className="btn btn-secondary"
              >
                Use a different email
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="centered-page">
      <PageTitle>Register</PageTitle>
      <div className="auth-container">
        <div className="auth-card">
          <h1 id="register-heading" ref={heading} tabIndex={-1}>Register</h1>

          <form
            onSubmit={e => void handleSubmit(e)}
            noValidate
            className="auth-form"
            aria-labelledby="register-heading"
          >
            <FormField
              id="email"
              label="Email"
              type="email"
              autoComplete="email"
              value={values.email}
              onChange={handleChange}
              error={errors.email}
              hint="We'll email you a link to choose a password."
              readOnly={submitting}
              required
              maxLength={EMAIL_MAX_LENGTH}
            />
            <p className="form-note">
              How we use your address: see the{' '}
              <Link to="/privacy" className="text-link">Privacy notice</Link>.
            </p>

            {error}

            <button type="submit" aria-disabled={submitting} className="btn btn-primary btn-block">
              {submitting ? 'Sending link...' : 'Continue'}
            </button>
          </form>

          <p className="auth-footer">
            Already have an account?{' '}
            <Link to="/login" className="text-link">Log in</Link>
          </p>
        </div>
      </div>
    </div>
  )
}
