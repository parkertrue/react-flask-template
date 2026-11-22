import { useState, type SubmitEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/auth/useAuth'
import { completePasswordReset } from '@/auth/authService'
import { linkProblemOf, useEmailLink, type LinkProblemKind } from '@/auth/emailLink'
import LinkProblem from '@/auth/LinkProblem'
import { errorCode, getErrorMessage } from '@/api/errors'
import FormField from '@/components/forms/FormField'
import { useFormFields } from '@/components/forms/useFormFields'
import PageTitle from '@/components/layout/PageTitle'
import type { LoginState } from './LoginPage'
import {
  validateNotGuessable,
  validatePassword,
  validatePasswordMatch,
  PASSWORD_MIN_LENGTH,
  PASSWORD_INPUT_MAX_LENGTH
} from '@/utils/validation'

// Why the link can't reset the password, in place of the form
const PROBLEMS: Record<LinkProblemKind, string> = {
  missing: 'This page needs the link from your email. Open the link in the email we sent you.',
  expired: 'This link has expired. Ask for a new one to reset your password.',
  invalid: 'This link is not valid. Copy the whole link from the email, or ask for a new one.',
  used: 'This link has already been used, or your password has changed since it was sent. Ask for a new one if you still need it.',
}

// A password reset's second step, the page the emailed link opens: the new
// password. The token proves the address; the backend sets the password and
// ends every session, this browser's too, and the user logs in with it.
// Not behind GuestRoute: a signed-in user's link would be lost to its
// redirect.
export default function CompletePasswordResetPage() {
  const { isAuthenticated, logout } = useAuth()
  const navigate = useNavigate()
  const link = useEmailLink()
  const { values, errors, handleChange, validate } = useFormFields({ password: '', confirmPassword: '' })
  const [formError, setFormError] = useState<string | null>(null)
  const [problem, setProblem] = useState<LinkProblemKind | null>(link.token ? null : 'missing')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e: SubmitEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (submitting || !link.token) return
    // The event's currentTarget is gone by the time the server answers
    const form = e.currentTarget

    const valid = validate(form, {
      password: validatePassword(values.password) ?? validateNotGuessable(values.password, link.email),
      confirmPassword: validatePasswordMatch(values.password, values.confirmPassword),
    })
    if (!valid) return

    setFormError(null)
    setSubmitting(true)
    try {
      await completePasswordReset(link.token, values.password)
      // The backend ended this browser's session with the others
      if (isAuthenticated) logout()
      const state: LoginState = { passwordReset: true }
      void navigate('/login', { replace: true, state })
    } catch (err) {
      setSubmitting(false)
      const code = errorCode(err)
      const refusal = linkProblemOf(err)
      if (refusal) setProblem(refusal)
      // The field's own message, focused, like a failed submit's
      else if (code === 'PASSWORD_BREACHED' || code === 'PASSWORD_GUESSABLE') {
        validate(form, { password: getErrorMessage(err) })
      }
      else setFormError(getErrorMessage(err))
    }
  }

  return (
    <div className="centered-page">
      <PageTitle>Choose a new password</PageTitle>
      <div className="auth-container">
        <div className="auth-card">
          <h1 id="reset-heading">Choose a new password</h1>

          {problem ? (
            <LinkProblem
              message={PROBLEMS[problem]}
              to="/password-reset"
              action="Ask for a new link"
              missing={problem === 'missing'}
            />
          ) : (
            <form
              onSubmit={e => void handleSubmit(e)}
              noValidate
              className="auth-form"
              aria-labelledby="reset-heading"
            >
              {/* The account's name, the token's, for password managers to update */}
              {link.email && <FormField
                id="email"
                label="Email"
                type="email"
                autoComplete="username"
                value={link.email}
                readOnly
              />}
              <FormField
                id="password"
                label="New password"
                type="password"
                autoComplete="new-password"
                value={values.password}
                onChange={handleChange}
                error={errors.password}
                hint={`At least ${PASSWORD_MIN_LENGTH} characters.`}
                readOnly={submitting}
                required
                maxLength={PASSWORD_INPUT_MAX_LENGTH}
              />
              <FormField
                id="confirmPassword"
                label="Confirm new password"
                type="password"
                autoComplete="new-password"
                value={values.confirmPassword}
                onChange={handleChange}
                error={errors.confirmPassword}
                readOnly={submitting}
                required
                maxLength={PASSWORD_INPUT_MAX_LENGTH}
              />

              {formError && <div className="error-message" role="alert">{formError}</div>}

              <button type="submit" aria-disabled={submitting} className="btn btn-primary btn-block">
                {submitting ? 'Saving...' : 'Save password'}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}
