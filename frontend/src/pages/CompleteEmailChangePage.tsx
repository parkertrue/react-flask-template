import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useAuth } from '@/auth/useAuth'
import { completeEmailChange, getAccount } from '@/auth/authService'
import { linkProblemOf, useEmailLink, type LinkProblemKind } from '@/auth/emailLink'
import LinkProblem from '@/auth/LinkProblem'
import { errorCode, getErrorMessage } from '@/api/errors'
import PageTitle from '@/components/layout/PageTitle'
import { ACCOUNT_QUERY_KEY } from './accountQuery'

// Why the link can't move the account, in place of its button
type Problem = LinkProblemKind | 'taken'

const PROBLEMS: Record<Problem, string> = {
  missing: 'This page needs the link from your email. Open the link in the email we sent your new address.',
  expired: 'This link has expired. Ask for a new one on your account page.',
  invalid: 'This link is not valid. Copy the whole link from the email, or ask for a new one on your account page.',
  used: 'This link has already been used, or your email or password has changed since it was sent.',
  taken: 'Another account has this email address now, so yours stays where it was.',
}

// An email change's second step, the page the link to the new address
// opens. A button, not a request as the page loads: some mail scanners open
// links, and moving the account is the user's to decide. Under no guard: the
// link may be opened on a device that is not signed in, or signed in as the
// account it moves.
export default function CompleteEmailChangePage() {
  const { isAuthenticated, updateEmail } = useAuth()
  const queryClient = useQueryClient()
  const link = useEmailLink()
  const [problem, setProblem] = useState<Problem | null>(link.token ? null : 'missing')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [movedTo, setMovedTo] = useState<string | null>(null)
  const done = useRef<HTMLParagraphElement>(null)

  // The button that had focus goes away: focus what replaced it
  useEffect(() => {
    if (movedTo) done.current?.focus()
  }, [movedTo])

  const handleConfirm = async () => {
    if (submitting || !link.token) return
    setError(null)
    setSubmitting(true)
    try {
      const { email } = await completeEmailChange(link.token)
      // This browser's session may be the account just moved, or another:
      // ask whose it is, so the navbar shows its address
      if (isAuthenticated) {
        await queryClient.query({ queryKey: ACCOUNT_QUERY_KEY, queryFn: getAccount, staleTime: 0 })
          .then(account => updateEmail(account.email), () => {})
      }
      setMovedTo(email)
    } catch (err) {
      setSubmitting(false)
      const code = errorCode(err)
      const refusal = linkProblemOf(err)
      if (refusal) setProblem(refusal)
      else if (code === 'EMAIL_ALREADY_REGISTERED') setProblem('taken')
      else setError(getErrorMessage(err))
    }
  }

  let content
  if (movedTo) {
    content = (
      <>
        <p ref={done} tabIndex={-1} className="success-message">
          Your email is now <strong>{movedTo}</strong>. Log in with it from now on.
        </p>
        <p className="auth-footer">
          {isAuthenticated
            ? <Link to="/account" className="text-link padded-link">Go to your account</Link>
            : <Link to="/login" className="text-link padded-link">Log in</Link>}
        </p>
      </>
    )
  } else if (problem) {
    content = (
      <LinkProblem
        message={PROBLEMS[problem]}
        to={isAuthenticated ? '/account' : '/login'}
        action={isAuthenticated ? 'Go to your account' : 'Log in'}
        missing={problem === 'missing'}
      />
    )
  } else {
    content = (
      <>
        <p>
          {link.email
            ? <>Move your account to <strong>{link.email}</strong>?</>
            : 'Move your account to the address this link was sent to?'}
        </p>
        {error && <div className="error-message" role="alert">{error}</div>}
        <button
          type="button"
          onClick={() => void handleConfirm()}
          aria-disabled={submitting}
          className="btn btn-primary btn-block"
        >
          {submitting ? 'Confirming...' : 'Confirm new email'}
        </button>
      </>
    )
  }

  return (
    <div className="centered-page">
      <PageTitle>Confirm your new email</PageTitle>
      <div className="auth-container">
        <div className="auth-card">
          <h1>Confirm your new email</h1>
          {content}
        </div>
      </div>
    </div>
  )
}
