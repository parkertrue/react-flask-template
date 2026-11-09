import { useEffect, useRef, useState, type ChangeEvent, type SubmitEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '@/auth/useAuth'
import { completeRegistration } from '@/auth/authService'
import { errorCode, getErrorMessage } from '@/api/errors'
import FormField from '@/components/forms/FormField'
import { useFormFields } from '@/components/forms/useFormFields'
import PageTitle from '@/components/layout/PageTitle'
import { TERMS_VERSION } from '@/legal'
import {
  validatePassword,
  validatePasswordMatch,
  PASSWORD_MIN_LENGTH,
  PASSWORD_MAX_LENGTH
} from '@/utils/validation'

// Why the link can't make an account, in place of the form
type LinkProblem = 'missing' | 'expired' | 'invalid' | 'registered'

const PROBLEMS: Record<LinkProblem, { message: string; to: string; action: string }> = {
  missing: {
    message: 'This page needs the link from your email. Open the link in the email we sent you.',
    to: '/register', action: 'Start again',
  },
  expired: {
    message: 'This link has expired. Ask for a new one to finish signing up.',
    to: '/register', action: 'Start again',
  },
  invalid: {
    message: 'This link is not valid. Copy the whole link from the email, or ask for a new one.',
    to: '/register', action: 'Start again',
  },
  registered: {
    message: 'This account is already set up.',
    to: '/login', action: 'Log in',
  },
}

// The link's fragment: #email=…&token=…. A fragment, not a query string, so
// the token never reaches a server's log (DECISIONS.md).
function readLink(hash: string) {
  const params = new URLSearchParams(hash.slice(1))
  return { email: params.get('email') ?? '', token: params.get('token') }
}

// Sign-up's second step, the page the emailed link opens: the password and
// the terms. The token proves the address; the backend makes the account
// and logs in, and GuestRoute moves the user on.
export default function CompleteRegistrationPage() {
  const { login } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  // Read once: the fragment is stripped from the address bar below
  const [link] = useState(() => readLink(location.hash))
  const { values, errors, handleChange, validate } = useFormFields({
    password: '', confirmPassword: '', acceptTerms: false
  })
  const [formError, setFormError] = useState<string | null>(null)
  const [problem, setProblem] = useState<LinkProblem | null>(link.token ? null : 'missing')
  const [submitting, setSubmitting] = useState(false)
  // The password rules stay hidden, to keep the form short, until a password
  // breaks one; from then on they show beside its message
  const [showPasswordRules, setShowPasswordRules] = useState(false)
  const problemMessage = useRef<HTMLParagraphElement>(null)

  // Off the address bar and out of history, so the token is not left where
  // the next person at this browser could find it. The state stays: where
  // GuestRoute sends the user once signed in.
  useEffect(() => {
    const state: unknown = location.state
    if (location.hash) void navigate({ pathname: location.pathname }, { replace: true, state })
  }, [location.hash, location.pathname, location.state, navigate])

  // The form, and the button that had focus, go away: focus what replaced it
  useEffect(() => {
    if (problem && problem !== 'missing') problemMessage.current?.focus()
  }, [problem])

  // readOnly doesn't stop a checkbox being ticked, so ignore it while busy
  const handleTermsChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (!submitting) handleChange(e)
  }

  const handleSubmit = async (e: SubmitEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (submitting || !link.token) return

    const passwordError = validatePassword(values.password)
    // Rendered by validate's flush, before it focuses the field
    if (passwordError) setShowPasswordRules(true)
    const valid = validate(e.currentTarget, {
      password: passwordError,
      confirmPassword: validatePasswordMatch(values.password, values.confirmPassword),
      acceptTerms: values.acceptTerms ? undefined : 'Accept the Terms and the Privacy notice to register',
    })
    if (!valid) return

    setFormError(null)
    setSubmitting(true)
    try {
      const tokens = await completeRegistration(link.token, values.password, TERMS_VERSION)
      // GuestRoute moves the user on once they are signed in
      login(tokens.access_token, tokens.refresh_csrf, link.email)
    } catch (err) {
      setSubmitting(false)
      const code = errorCode(err)
      if (code === 'LINK_EXPIRED') setProblem('expired')
      else if (code === 'LINK_INVALID') setProblem('invalid')
      else if (code === 'EMAIL_ALREADY_REGISTERED') setProblem('registered')
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

          {shown ? (
            <>
              <p
                ref={problemMessage}
                tabIndex={-1}
                className={problem === 'missing' ? 'info-message' : 'error-message'}
                role={problem === 'missing' ? undefined : 'alert'}
              >
                {shown.message}
              </p>
              <p className="auth-footer">
                <Link to={shown.to} className="text-link">{shown.action}</Link>
              </p>
            </>
          ) : (
            <form
              onSubmit={e => void handleSubmit(e)}
              noValidate
              className="auth-form"
              aria-labelledby="complete-heading"
            >
              {/* The account's name, which the link chose, for password managers to save */}
              <FormField
                id="email"
                label="Email"
                type="email"
                autoComplete="username"
                value={link.email}
                readOnly
              />
              <FormField
                id="password"
                label="Password"
                type="password"
                autoComplete="new-password"
                value={values.password}
                onChange={handleChange}
                error={errors.password}
                hint={showPasswordRules
                  ? `At least ${PASSWORD_MIN_LENGTH} characters, with an uppercase letter, a lowercase letter and a number.`
                  : undefined}
                readOnly={submitting}
                required
                maxLength={PASSWORD_MAX_LENGTH}
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
                maxLength={PASSWORD_MAX_LENGTH}
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
