import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { registerUser } from '@/auth/authService'
import { getErrorMessage } from '@/api/errors'
import FormField from '@/components/forms/FormField'
import { useFormFields } from '@/components/forms/useFormFields'
import PageTitle from '@/components/layout/PageTitle'
import { TERMS_VERSION } from '@/legal'
import {
  validateEmail,
  validatePassword,
  validatePasswordMatch,
  EMAIL_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
  PASSWORD_MAX_LENGTH
} from '@/utils/validation'

export default function RegisterPage() {
  const navigate = useNavigate()
  const { values, errors, handleChange, validate } = useFormFields({
    email: '', password: '', confirmPassword: '', acceptTerms: false
  })
  // The submit event's form is gone by the time the server answers
  const form = useRef(null)
  const [formError, setFormError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  // The password rules stay hidden, to keep the form short, until a password
  // breaks one; from then on they show beside its message
  const [showPasswordRules, setShowPasswordRules] = useState(false)

  // readOnly doesn't stop a checkbox being ticked, so ignore it while busy
  const handleTermsChange = (e) => {
    if (!submitting) handleChange(e)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (submitting) return

    const passwordError = validatePassword(values.password)
    // Rendered by validate's flush, before it focuses the field
    if (passwordError) setShowPasswordRules(true)
    const valid = validate(e.currentTarget, {
      email: validateEmail(values.email),
      password: passwordError,
      confirmPassword: validatePasswordMatch(values.password, values.confirmPassword),
      acceptTerms: values.acceptTerms ? undefined : 'Accept the Terms and the Privacy notice to register',
    })
    if (!valid) return

    setFormError(null)
    setSubmitting(true)
    try {
      await registerUser(values.email, values.password, TERMS_VERSION)
      navigate('/login', { state: { registered: true } })
    } catch (err) {
      setSubmitting(false)
      if (err.response?.data?.error?.code === 'EMAIL_ALREADY_REGISTERED') {
        // The field's own message, focused, like a failed submit's
        validate(form.current, { email: getErrorMessage(err) })
      } else {
        setFormError(getErrorMessage(err))
      }
    }
  }

  return (
    <div className="centered-page">
      <PageTitle>Register</PageTitle>
      <div className="auth-container">
        <div className="auth-card">
          <h1 id="register-heading">Register</h1>

          <form
            ref={form}
            onSubmit={handleSubmit}
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
              readOnly={submitting}
              required
              maxLength={EMAIL_MAX_LENGTH}
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
              {submitting ? 'Creating account...' : 'Register'}
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
