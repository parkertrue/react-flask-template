import { NavLink } from 'react-router-dom'
import { useAuth } from '@/auth/useAuth'
import LogoutButton from '@/auth/LogoutButton'

export default function Navbar() {
  const { email, isAuthenticated } = useAuth()

  // NavLink marks the current page's link: aria-current="page" for screen
  // readers, the "active" class for the eye
  return (
    <header className="navbar">
      <div className="navbar-container">
        <nav aria-label="Main" className="navbar-links">
          <NavLink to="/" end className="nav-link">Home</NavLink>
          {isAuthenticated ? (
            <NavLink to="/notes" className="nav-link">My notes</NavLink>
          ) : (
            <>
              <NavLink to="/login" className="nav-link">Log in</NavLink>
              <NavLink to="/register" className="nav-link">Register</NavLink>
            </>
          )}
        </nav>

        {isAuthenticated && (
          <div className="navbar-user">
            {/* The name starts with the visible email, so voice control
                users can say what they see */}
            <NavLink to="/account" className="user-email" aria-label={`${email} (account)`}>
              {email}
            </NavLink>
            <LogoutButton />
          </div>
        )}
      </div>
    </header>
  )
}
