import { describe, it, expect } from 'vitest'
import type { ComponentType } from 'react'
import { screen, within } from '@testing-library/react'
import PrivacyPage from '../PrivacyPage'
import TermsPage from '../TermsPage'
import ContactPage from '../ContactPage'
import { renderRoutes } from '@/test/router'
import { APP_NAME } from '@/appName'
import { OPERATOR, TERMS_VERSION } from '@/legal'

function renderPage(Page: ComponentType) {
  return renderRoutes([{ path: '/', element: <Page /> }], '/')
}

describe.each([
  ['PrivacyPage', PrivacyPage, 'Privacy notice'],
  ['TermsPage', TermsPage, 'Terms of service'],
  ['ContactPage', ContactPage, 'Contact'],
])('%s', (_, Page, title) => {
  it('has its title and heading, says it is a placeholder, and gives the contact email', () => {
    renderPage(Page)

    expect(screen.getByRole('heading', { level: 1, name: title })).toBeInTheDocument()
    expect(document.title).toBe(`${title} | ${APP_NAME}`)
    expect(screen.getByText(/^Placeholder: /)).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: OPERATOR.email })[0])
      .toHaveAttribute('href', `mailto:${OPERATOR.email}`)
  })
})

describe('TermsPage', () => {
  it('names the version that registering accepts, and links the privacy notice', () => {
    renderPage(TermsPage)

    expect(screen.getByText(new RegExp(`^Version ${TERMS_VERSION}, `))).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'privacy notice' })).toHaveAttribute('href', '/privacy')
  })
})

describe('PrivacyPage', () => {
  it('names the operator and links the contact page', () => {
    renderPage(PrivacyPage)

    const contactLink = screen.getByRole('link', { name: 'contact page' })
    expect(contactLink).toHaveAttribute('href', '/contact')
    expect(contactLink.closest('p')).toHaveTextContent(`${OPERATOR.name} runs this service`)
  })
})

describe('ContactPage', () => {
  it('gives the operator\'s name and address, and where to report a security problem', () => {
    renderPage(ContactPage)

    const address = within(screen.getByRole('group'))
    expect(address.getByText(OPERATOR.name, { exact: false })).toHaveTextContent(OPERATOR.address)
    expect(screen.getByRole('link', { name: 'security.txt' }))
      .toHaveAttribute('href', '/.well-known/security.txt')
  })
})
