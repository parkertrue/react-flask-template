import { useId, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { endSession, listSessions, type Sessions } from '@/auth/authService'
import type { SessionResponse } from '@/api/schemas'
import { errorResponse, getErrorMessage } from '@/api/errors'

const SESSIONS_KEY = ['sessions']

// A time a session did something, in the reader's own zone and words
function when(iso: string) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

interface SessionListProps {
  // Where focus goes when the last button it could move to is gone
  fallbackFocus: () => void
}

// The account's live sessions, each named by its device, with "Log out" on
// every one but this browser's (ASVS 7.5.2). Logging a device out can be
// undone by logging in again, so it does not ask first.
export default function SessionList({ fallbackFocus }: SessionListProps) {
  const queryClient = useQueryClient()
  const timesId = useId()
  // Refetched when the window regains focus: another device may have
  // signed in or out meanwhile
  const { data, error: loadError } = useQuery({
    queryKey: SESSIONS_KEY, queryFn: listSessions, refetchOnWindowFocus: true,
  })
  const [ending, setEnding] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Which device was logged out, on the persistent status line
  const [status, setStatus] = useState('')
  const buttons = useRef(new Map<string, HTMLButtonElement>())

  // shown: the list as rendered, which the click was made on
  const handleEnd = async ({ id, device }: SessionResponse, shown: Sessions) => {
    if (ending) return
    setEnding(id)
    setError(null)
    setStatus('')
    try {
      await endSession(id)
      setStatus(`Logged out ${device}.`)
    } catch (err) {
      // A 404: it ended on its own, or from elsewhere, before this click
      if (errorResponse(err)?.status === 404) {
        setStatus(`${device} was already logged out.`)
      } else {
        setEnding(null)
        setError(getErrorMessage(err))
        return
      }
    }
    // Its button goes with it: focus the next device's, else what is left
    const others = shown.sessions.filter(session => !session.current)
    const index = others.findIndex(session => session.id === id)
    const next = others[index + 1] ?? others[index - 1]
    queryClient.setQueryData<Sessions>(SESSIONS_KEY, {
      sessions: shown.sessions.filter(session => session.id !== id),
    })
    setEnding(null)
    const button = next && buttons.current.get(next.id)
    if (button) button.focus()
    else fallbackFocus()
  }

  return (
    <>
      {loadError && <div className="error-message" role="alert">{getErrorMessage(loadError)}</div>}
      {!data && !loadError && <p>Loading sessions...</p>}
      {data && (
        <ul className="session-list" aria-label="Signed-in devices">
          {data.sessions.map(session => (
            <li key={session.id} className="session-item">
              <div>
                <strong>{session.device}</strong>
                {session.current && <span> (this device)</span>}
                <br />
                <span className="session-times" id={`${timesId}-${session.id}`}>
                  Signed in <time dateTime={session.signed_in_at}>{when(session.signed_in_at)}</time>
                  {' · '}last active <time dateTime={session.last_active_at}>{when(session.last_active_at)}</time>
                </span>
              </div>
              {!session.current && (
                <button
                  type="button"
                  ref={button => {
                    if (button) buttons.current.set(session.id, button)
                    else buttons.current.delete(session.id)
                  }}
                  onClick={() => void handleEnd(session, data)}
                  aria-disabled={ending !== null}
                  aria-label={`${ending === session.id ? 'Logging out' : 'Log out'} ${session.device}`}
                  // Its times tell apart two devices of the same name
                  aria-describedby={`${timesId}-${session.id}`}
                  className="btn btn-secondary"
                >
                  {ending === session.id ? 'Logging out...' : 'Log out'}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {error && <div className="error-message" role="alert">{error}</div>}
      <p className="visually-hidden" role="status">{status}</p>
    </>
  )
}
