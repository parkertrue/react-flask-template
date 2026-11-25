import { useState, type ChangeEvent, type SubmitEvent } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '@/auth/useAuth'
import { linkProblemOf, useEmailLink, type LinkProblemKind } from '@/auth/emailLink'
import LinkProblem from '@/auth/LinkProblem'
import { completeRegistration } from '@/auth/authService'
import { errorCode, getErrorMessage } from '@/api/errors'
import FormField from '@/components/forms/FormField'
import { useFormFields } from '@/components/forms/useFormFields'
import PageTitle from '@/components/layout/PageTitle'
import { TERMS_VERSION } from '@/appInfo'
import {
  validateNotGuessable,
  validatePassword,
  validatePasswordMatch,
  PASSWORD_MIN_LENGTH,
  PASSWORD_INPUT_MAX_LENGTH
} from '@/utils/validation'

// Why the link can't make an account, in place of the form
type Problem = LinkProblemKind | 'registered'

const PROBLEMS: Record<Problem, { message: string; to: string; action: string }> = {
  missing: {
    message: 'This page needs the link from your email. Open the link in the email we sent you.',
    to: '/signup', action: 'Start again',
  },
  expired: {
    message: 'This link has expired. Ask for a new one to finish signing up.',
    to: '/signup', action: 'Start again',
  },
  invalid: {
    message: 'This link is not valid. Copy the whole link from the email, or ask for a new one.',
    to: '/signup', action: 'Start again',
  },
  used: {
    message: 'This link has already been used. Sign up again for a new one.',
    to: '/signup', action: 'Start again',
  },
  registered: {
    message: 'This account is already set up.',
    to: '/login', action: 'Log in',
  },
}

// Sign-up's second step, the page the emailed link opens: the password and
// the terms. The token proves the address; the backend makes the account
// and logs in, and GuestRoute moves the user on.
export default function CompleteRegistrationPage() {
  const { login } = useAuth()
  const link = useEmailLink()
  const { values, errors, handleChange, validate } = useFormFields({
    password: '', confirmPassword: '', acceptTerms: false
  })
  const [formError, setFormError] = useState<string | null>(null)
  const [problem, setProblem] = useState<Problem | null>(link.token ? null : 'missing')
  const [submitting, setSubmitting] = useState(false)

  // readOnly doesn't stop a checkbox being ticked, so ignore it while busy
  const handleTermsChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (!submitting) handleChange(e)
  }

  const handleSubmit = async (e: SubmitEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (submitting || !link.token) return
    // The event's currentTarget is gone by the time the server answers
    const form = e.currentTarget

    const valid = validate(form, {
      password: validatePassword(values.password) ?? validateNotGuessable(values.password, link.email),
      confirmPassword: validatePasswordMatch(values.password, values.confirmPassword),
      acceptTerms: values.acceptTerms ? undefined : 'Accept the Terms and the Privacy notice to sign up',
    })
    if (!valid) return

    setFormError(null)
    setSubmitting(true)
    try {
      const account = await completeRegistration(link.token, values.password, TERMS_VERSION)
      // Under the address the server made the account for. GuestRoute moves
      // the user on once they are signed in.
      login(account.access_token, account.refresh_csrf, account.email)
    } catch (err) {
      setSubmitting(false)
      const code = errorCode(err)
      const refusal = linkProblemOf(err)
      if (refusal) setProblem(refusal)
      else if (code === 'EMAIL_ALREADY_REGISTERED') setProblem('registered')
      // The field's own message, focused, like a failed submit's
      else if (code === 'PASSWORD_BREACHED' || code === 'PASSWORD_GUESSABLE') {
        validate(form, { password: getErrorMessage(err) })
      }
      else setFormError(getErrorMessage(err))
    }
  }

  const shown = problem && PROBLEMS[problem]

  return (
    <div className="centered-page">
      <PageTitle>Finish signing up</PageTitle>
      <div className="auth-container">
        <div className="auth-card">
          <h1 id="complete-heading">Finish signing up</h1>

          {/* In full: the read-only field below cuts a long address off */}
          {!shown && link.email && <p>For <strong>{link.email}</strong></p>}

          {shown ? (
            <LinkProblem {...shown} missing={problem === 'missing'} />
          ) : (
            <form
              onSubmit={e => void handleSubmit(e)}
              noValidate
              className="auth-form"
              aria-labelledby="complete-heading"
            >
              {/* The account's name, the token's, for password managers to save */}
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
                label="Password"
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
                label="Confirm password"
                type="password"
                autoComplete="new-password"
                value={values.confirmPassword}
                onChange={handleChange}
                error={errors.confirmPassword}
                readOnly={submitting}
                required
                maxLength={PASSWORD_INPUT_MAX_LENGTH}
              />
              <FormField
                id="acceptTerms"
                type="checkbox"
                label={<>
                  I accept the <Link to="/terms" target="_blank" aria-describedby="new-tab-note" className="text-link">Terms</Link> and
                  the <Link to="/privacy" target="_blank" aria-describedby="new-tab-note" className="text-link">Privacy notice</Link>
                  {/* Read with each link, never shown, and left out of the checkbox's name */}
                  <span id="new-tab-note" hidden>Opens in a new tab.</span>
                </>}
                checked={values.acceptTerms}
                onChange={handleTermsChange}
                error={errors.acceptTerms}
                aria-readonly={submitting}
              />

              {formError && <div className="error-message" role="alert">{formError}</div>}

              <button type="submit" aria-disabled={submitting} className="btn btn-primary btn-block">
                {submitting ? 'Creating account...' : 'Create account'}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}
