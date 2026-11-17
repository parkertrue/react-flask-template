import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

// What an emailed link's page reads from it: the token, and the address it
// names ('' when it can't be read)
export interface EmailLink {
  token: string | null
  email: string
}

// The link's fragment: #token=…. A fragment, not a query string, so the
// token never reaches a server's log (DECISIONS.md). Anything else the link
// carries is ignored: only the token decides the account.
export function readLink(hash: string): EmailLink {
  const token = new URLSearchParams(hash.slice(1)).get('token')
  return { token, email: tokenEmail(token) }
}

// The address a token names, to show for password managers. Its first part
// is the payload, base64url JSON, signed but not encrypted: [email, state]
// (backend/app/utils/links.py). One that starts with '.' is compressed,
// which only a long, repetitive address makes: none is shown then, and the
// backend still uses the token's.
export function tokenEmail(token: string | null) {
  try {
    const payload = token?.split('.')[0] ?? ''
    const value: unknown = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')))
    const email: unknown = Array.isArray(value) ? value[0] : undefined
    return typeof email === 'string' ? email : ''
  } catch {
    return ''
  }
}

// The link of the page's address, read once, then stripped off the address
// bar and out of history, so the token is not left where the next person at
// this browser could find it. The location's state stays: where GuestRoute
// sends the user once signed in.
export function useEmailLink() {
  const location = useLocation()
  const navigate = useNavigate()
  const [link] = useState(() => readLink(location.hash))

  useEffect(() => {
    const state: unknown = location.state
    if (location.hash) void navigate({ pathname: location.pathname }, { replace: true, state })
  }, [location.hash, location.pathname, location.state, navigate])

  return link
}
