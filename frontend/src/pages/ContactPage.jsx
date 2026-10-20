import PageTitle from '@/components/layout/PageTitle'
import { OPERATOR } from '@/legal'
import PlaceholderNotice from './PlaceholderNotice'

// Who runs the service and how to reach them: the operator's details (an
// imprint, where the law asks for one), the users' point of contact, and
// where to report an accessibility barrier or a security problem
export default function ContactPage() {
  const email = <a href={`mailto:${OPERATOR.email}`} className="text-link">{OPERATOR.email}</a>

  return (
    <div className="legal-page page-column">
      <PageTitle>Contact</PageTitle>
      <h1>Contact</h1>
      <PlaceholderNotice />

      <h2>Who runs this service</h2>
      <address>
        {OPERATOR.name}<br />
        {OPERATOR.address}<br />
        Email: {email}
      </address>
      <p>
        Write to us in [the languages you answer in] about anything to do
        with the service, your account or your data. [Add any registration or
        VAT number the law requires you to show.]
      </p>

      <h2>Accessibility</h2>
      <p>
        We aim to meet the Web Content Accessibility Guidelines (WCAG) 2.2 at
        level AA. [List any part of the service known not to meet it yet.] If
        something keeps you from using the service, tell us at {email} and we
        will help, and fix it.
      </p>

      <h2>Security</h2>
      <p>
        To report a security problem, see
        our <a href="/.well-known/security.txt" className="text-link">security.txt</a>, or write
        to {email}.
      </p>
    </div>
  )
}
