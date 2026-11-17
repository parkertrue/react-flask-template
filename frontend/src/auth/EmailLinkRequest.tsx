import { useEffect, useRef, useState, type ReactNode, type SubmitEvent } from 'react'
import { getErrorMessage } from '@/api/errors'
import FormField from '@/components/forms/FormField'
import { useFormFields } from '@/components/forms/useFormFields'
import PageTitle from '@/components/layout/PageTitle'
import { validateEmail, EMAIL_MAX_LENGTH } from '@/utils/validation'

interface EmailLinkRequestProps {
  // The page's title and heading
  title: string
  // The email field's hint: what the link is for
  hint: string
  // The submit button's label, and its label while sending
  submitLabel: string
  busyLabel: string
  // Asks the backend to email the address a link; it answers alike whether
  // the address has an account or not, so the page never says which
  send: (email: string) => Promise<void>
  // What the inbox step says was sent to the address
  sentText: (email: string) => ReactNode
  // Under the email field: a note on the address's use
  note?: ReactNode
  // Under the form: where else to go
  footer: ReactNode
}

// The first step of a flow an emailed link finishes (sign-up, a password
// reset): the address, then "Check your inbox", with "Send again" and "Use a
// different email". The link's page does the rest.
export default function EmailLinkRequest(props: EmailLinkRequestProps) {
  const { title, hint, submitLabel, busyLabel, send, sentText, note, footer } = props
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

  const sendLink = async (email: string) => {
    setFormError(null)
    setStatus('')
    setSubmitting(true)
    try {
      await send(email)
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

    if (await sendLink(values.email)) setSentTo(values.email)
  }

  const handleSendAgain = async () => {
    if (submitting || sentTo === null) return
    if (await sendLink(sentTo)) setStatus(`Sent again to ${sentTo}.`)
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
            <p className="sent-to">{sentText(sentTo)}</p>
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
      <PageTitle>{title}</PageTitle>
      <div className="auth-container">
        <div className="auth-card">
          <h1 id="email-link-heading" ref={heading} tabIndex={-1}>{title}</h1>

          <form
            onSubmit={e => void handleSubmit(e)}
            noValidate
            className="auth-form"
            aria-labelledby="email-link-heading"
          >
            <FormField
              id="email"
              label="Email"
              type="email"
              autoComplete="email"
              value={values.email}
              onChange={handleChange}
              error={errors.email}
              hint={hint}
              readOnly={submitting}
              required
              maxLength={EMAIL_MAX_LENGTH}
            />
            {note}

            {error}

            <button type="submit" aria-disabled={submitting} className="btn btn-primary btn-block">
              {submitting ? busyLabel : submitLabel}
            </button>
          </form>

          {footer}
        </div>
      </div>
    </div>
  )
}
