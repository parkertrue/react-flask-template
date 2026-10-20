import { Link } from 'react-router-dom'
import { APP_NAME } from '@/appName'
import { useAuth } from '@/auth/useAuth'
import PageTitle from '@/components/layout/PageTitle'
import ApiStatus from '@/features/health/ApiStatus'

export default function HomePage() {
  const { isAuthenticated } = useAuth()

  return (
    <div className="centered-page">
      <PageTitle />
      <div className="home-content">
        <h1>Welcome to {APP_NAME}</h1>
        <p>A full-stack starter with auth, plus dev, test and production setups.</p>
        <ApiStatus />

        <div className="home-actions">
          {isAuthenticated ? (
            <Link to="/notes" className="btn btn-primary">View my notes</Link>
          ) : (
            <>
              <Link to="/register" className="btn btn-primary">Get started</Link>
              <Link to="/login" className="btn btn-secondary">Log in</Link>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
