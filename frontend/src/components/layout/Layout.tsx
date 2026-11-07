import { useEffect, useRef } from 'react'
import { Outlet, ScrollRestoration, useLocation } from 'react-router-dom'
import Navbar from './Navbar'
import Footer from './Footer'

export default function Layout() {
  const { pathname } = useLocation()
  const mainRef = useRef<HTMLElement>(null)
  const shownPath = useRef(pathname)

  // Changing pages in an SPA leaves focus on the link just used, so a screen
  // reader announces nothing. Focus the new page's h1 instead: screen readers
  // read the heading, which names the page, and the next Tab starts at the
  // top of its content. <main> stands in for a page without one. The first
  // page keeps the browser's default.
  useEffect(() => {
    if (shownPath.current === pathname) return
    shownPath.current = pathname
    const heading = mainRef.current?.querySelector('h1')
    if (heading) {
      heading.tabIndex = -1
      heading.focus()
    } else {
      mainRef.current?.focus()
    }
  }, [pathname])

  return (
    <div className="layout">
      <Navbar />
      <main className="main-content" ref={mainRef} tabIndex={-1}>
        <Outlet />
      </main>
      <Footer />
      <ScrollRestoration />
    </div>
  )
}
