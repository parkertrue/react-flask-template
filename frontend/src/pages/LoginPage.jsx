import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useAuth } from '@/auth/useAuth'
import { loginUser } from '@/auth/authService'
import { getErrorMessage } from '@/api/errors'
import FormField from '@/components/forms/FormField'
import { useFormFields } from '@/components/forms/useFormFields'
import PageTitle from '@/components/layout/PageTitle'
import {
  validateEmail,
  validatePassword,
  PASSWORD_MAX_LENGTH,
  EMAIL_MAX_LENGTH
} from '@/utils/validation'

export default function LoginPage() {
  const { login, sessionEnded } = useAuth()
  const location = useLocation()
  // Where the user came from: registering, or deleting their account
  const { registered, accountDeleted } = location.state ?? {}
  const { values, errors, handleChange, validate } = useFormFields({ email: '', password: '' })
  const [formError, setFormError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  // Why the user is here, for screen readers. Filled after the first render:
  // a live region added along with its text is not read.
  const [status, setStatus] = useState('')
  const notice = registered
    ? 'Registration successful. Please log in.'
    : accountDeleted ? 'Your account has been deleted.'
      : sessionEnded ? 'Your session has ended. Please log in again.' : ''

  useEffect(() => {
    // Announcing the notice once the region exists is what this effect is for
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStatus(notice)
  }, [notice])

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (submitting) return

    const valid = validate(e.currentTarget, {
      email: validateEmail(values.email),
      password: validatePassword(values.password),
    })
    if (!valid) return

    setFormError(null)
    setSubmitting(true)
    try {
      const data = await loginUser(values.email, values.password)
      // GuestRoute moves the user on once they are signed in
      login(data.access_token, data.refresh_csrf, values.email)
    } catch (err) {
      setFormError(getErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="centered-page">
      <PageTitle>Log in</PageTitle>
      <div className="auth-container">
        <div className="auth-card">
          <h1 id="login-heading">Log in</h1>

          {notice && (
            <p className={registered || accountDeleted ? 'success-message' : 'info-message'}>{notice}</p>
          )}
          <p className="visually-hidden" role="status">{status}</p>

          <form
            onSubmit={handleSubmit}
            noValidate
            className="auth-form"
            aria-labelledby="login-heading"
          >
            <FormField
              id="email"
              label="Email"
              type="email"
              autoComplete="email"
              value={values.email}
              onChange={handleChange}
              error={errors.email}
              readOnly={submitting}
              required
              maxLength={EMAIL_MAX_LENGTH}
            />
            <FormField
              id="password"
              label="Password"
              type="password"
              autoComplete="current-password"
              value={values.password}
              onChange={handleChange}
              error={errors.password}
              readOnly={submitting}
              required
              maxLength={PASSWORD_MAX_LENGTH}
            />

            {formError && <div className="error-message" role="alert">{formError}</div>}

            <button type="submit" aria-disabled={submitting} className="btn btn-primary btn-block">
              {submitting ? 'Logging in...' : 'Log in'}
            </button>
          </form>

          <p className="auth-footer">
            Don't have an account?{' '}
            <Link to="/register" className="text-link">Register</Link>
          </p>
        </div>
      </div>
    </div>
  )
}
