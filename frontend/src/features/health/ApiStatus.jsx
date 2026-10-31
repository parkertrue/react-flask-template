import { useHealth } from './useHealth'
import './health.css'

// The dot's color for each status; anything else shows as still checking
const DOT = { ok: 'api-status-up', error: 'api-status-down' }

// An example like the notes feature (a polled backend call): delete this
// folder when starting a real app. The backend's /api/health stays, since the
// Docker healthchecks and Playwright use it.
export default function ApiStatus() {
  const status = useHealth()

  return (
    <div className="api-status">
      <p role="status" className={DOT[status]}>API status: {status}</p>
    </div>
  )
}
