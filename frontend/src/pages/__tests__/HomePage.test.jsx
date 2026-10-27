import { describe, it, expect, vi } from 'vitest'
import { screen } from '@testing-library/react'
import HomePage from '../HomePage'
import { renderRoutes, signIn } from '@/test/router'
import { APP_NAME, APP_TAGLINE } from '@/appName'

vi.mock('@/features/health/ApiStatus', () => ({ default: () => null }))

function renderPage() {
  renderRoutes([{ path: '/', element: <HomePage /> }])
}

const links = () => Object.fromEntries(
  screen.getAllByRole('link').map(link => [link.textContent, link.getAttribute('href')])
)

describe('HomePage', () => {
  it('welcomes the visitor', () => {
    renderPage()

    expect(screen.getByRole('heading', { level: 1, name: `Welcome to ${APP_NAME}` })).toBeInTheDocument()
    expect(screen.getByText(APP_TAGLINE)).toBeInTheDocument()
    expect(document.title).toBe(APP_NAME)
  })

  it('offers a visitor registration and login', () => {
    renderPage()

    expect(links()).toEqual({ 'Get started': '/register', 'Log in': '/login' })
  })

  it('offers a signed-in user their notes instead', () => {
    signIn()
    renderPage()

    expect(links()).toEqual({ 'View my notes': '/notes' })
  })
})
