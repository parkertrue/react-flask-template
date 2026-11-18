import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '@/auth/useAuth'
import { undoEmailChange } from '@/auth/authService'
import { useEmailLink } from '@/auth/emailLink'
import LinkProblem from '@/auth/LinkProblem'
import { errorCode, getErrorMessage } from '@/api/errors'
import PageTitle from '@/components/layout/PageTitle'

// Why the link can't move the account back, in place of its button
type LinkProblemKind = 'missing' | 'expired' | 'invalid' | 'used' | 'taken'

const PROBLEMS: Record<LinkProblemKind, string> = {
  missing: 'This page needs the link from the email that told you your address had changed.',
  expired: 'This link has expired. If you did not change your email, contact us.',
  invalid: 'This link is not valid. Copy the whole link from the email.',
  used: 'Your account is already at this address.',
  taken: 'Another account has this address now, so yours cannot move back to it. Contact us.',
}

// The page the old address's link opens, after an email change its owner
// may not have made: moves the account back and logs out every device. A
// button, not a request as the page loads (mail scanners open links). Then
// the owner resets the password, which whoever made the change may know.
export default function UndoEmailChangePage() {
  const { isAuthenticated, logout } = useAuth()
  const link = useEmailLink()
  const [problem, setProblem] = useState<LinkProblemKind | null>(link.token ? null : 'missing')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [movedTo, setMovedTo] = useState<string | null>(null)
  const done = useRef<HTMLParagraphElement>(null)

  useEffect(() => {
    if (movedTo) done.current?.focus()
  }, [movedTo])

  const handleUndo = async () => {
    if (submitting || !link.token) return
    setError(null)
    setSubmitting(true)
    try {
      const { email } = await undoEmailChange(link.token)
      // The backend ended every session, this browser's too
      if (isAuthenticated) logout()
      setMovedTo(email)
    } catch (err) {
      setSubmitting(false)
      const code = errorCode(err)
      if (code === 'LINK_EXPIRED') setProblem('expired')
      else if (code === 'LINK_INVALID') setProblem('invalid')
      else if (code === 'LINK_USED') setProblem('used')
      else if (code === 'EMAIL_ALREADY_REGISTERED') setProblem('taken')
      else setError(getErrorMessage(err))
    }
  }

  let content
  if (movedTo) {
    content = (
      <>
        <p ref={done} tabIndex={-1} className="success-message">
          Your account is back at <strong>{movedTo}</strong>, and every device was logged out.
          Reset your password now: whoever changed your email may know it.
        </p>
        <p className="auth-footer">
          <Link to="/password-reset" className="text-link padded-link">Reset your password</Link>
        </p>
      </>
    )
  } else if (problem) {
    content = (
      <LinkProblem
        message={PROBLEMS[problem]}
        to={problem === 'used' ? '/login' : '/contact'}
        action={problem === 'used' ? 'Log in' : 'Contact us'}
        missing={problem === 'missing'}
      />
    )
  } else {
    content = (
      <>
        <p>
          {link.email
            ? <>Move your account back to <strong>{link.email}</strong>?</>
            : 'Move your account back to the address this link was sent to?'}
          {' '}Every device signed in to it will be logged out.
        </p>
        {error && <div className="error-message" role="alert">{error}</div>}
        <button
          type="button"
          onClick={() => void handleUndo()}
          aria-disabled={submitting}
          className="btn btn-danger btn-block"
        >
          {submitting ? 'Moving it back...' : 'Move my account back'}
        </button>
      </>
    )
  }

  return (
    <div className="centered-page">
      <PageTitle>Undo an email change</PageTitle>
      <div className="auth-container">
        <div className="auth-card">
          <h1>Undo an email change</h1>
          {content}
        </div>
      </div>
    </div>
  )
}
