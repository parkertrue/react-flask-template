import { describe, it, expect } from 'vitest'
import { screen, within } from '@testing-library/react'
import Navbar from '../Navbar'
import { renderRoutes, signIn } from '@/test/router'

function renderNavbar(path) {
  renderRoutes([{ path: '*', element: <Navbar /> }], path)
}

/** The main navigation's links, as { text: href } */
const links = () => Object.fromEntries(
  within(screen.getByRole('navigation', { name: 'Main' })).getAllByRole('link')
    .map(link => [link.textContent, link.getAttribute('href')])
)

const current = () => screen.getAllByRole('link')
  .filter(link => link.getAttribute('aria-current') === 'page')
  .map(link => link.textContent)

describe('Navbar', () => {
  it('offers a visitor the way in', () => {
    renderNavbar('/')

    expect(links()).toEqual({ Home: '/', 'Log in': '/login', Register: '/register' })
    expect(screen.queryByRole('button', { name: 'Log out' })).not.toBeInTheDocument()
  })

  it('offers a signed-in user their notes, account and logout', () => {
    signIn('user@example.com')
    renderNavbar('/')

    expect(links()).toEqual({ Home: '/', 'My notes': '/notes' })
    // The email is the account link; its name says where it goes
    expect(screen.getByRole('link', { name: 'user@example.com (account)' }))
      .toHaveAttribute('href', '/account')
    expect(screen.getByRole('button', { name: 'Log out' })).toBeInTheDocument()
  })

  it.each([
    ['/', ['Home']],
    ['/login', ['Log in']],
    ['/register', ['Register']],
  ])('marks the link to %s as the current page', (path, expected) => {
    renderNavbar(path)

    expect(current()).toEqual(expected)
  })

  it.each([
    ['/notes', ['My notes']],
    ['/account', ['user@example.com']],
  ])('marks the link to %s as the current page when signed in', (path, expected) => {
    signIn('user@example.com')
    renderNavbar(path)

    expect(current()).toEqual(expected)
  })
})
