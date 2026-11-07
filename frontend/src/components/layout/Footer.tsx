import { NavLink } from 'react-router-dom'

// On every page, so the privacy notice, the terms and the operator's contact
// details are always one step away
export default function Footer() {
  return (
    <footer className="footer">
      <nav aria-label="Legal" className="footer-links">
        <NavLink to="/privacy" className="text-link footer-link">Privacy</NavLink>
        <NavLink to="/terms" className="text-link footer-link">Terms</NavLink>
        <NavLink to="/contact" className="text-link footer-link">Contact</NavLink>
      </nav>
    </footer>
  )
}
