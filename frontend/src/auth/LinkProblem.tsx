import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'

interface LinkProblemProps {
  // Why the link cannot be used
  message: string
  // What to do instead
  to: string
  action: string
  // No link at all: a page reached some other way, told what it needs, not
  // an error, and left where focus already is
  missing?: boolean
}

// What an emailed link's page shows in place of its form when the link is
// missing or refused. A refusal replaces the form, and the button that had
// focus, so focus moves to the reason.
export default function LinkProblem({ message, to, action, missing = false }: LinkProblemProps) {
  const reason = useRef<HTMLParagraphElement>(null)

  useEffect(() => {
    if (!missing) reason.current?.focus()
  }, [missing])

  return (
    <>
      <p
        ref={reason}
        tabIndex={-1}
        className={missing ? 'info-message' : 'error-message'}
        role={missing ? undefined : 'alert'}
      >
        {message}
      </p>
      <p className="auth-footer">
        <Link to={to} className="text-link padded-link">{action}</Link>
      </p>
    </>
  )
}
