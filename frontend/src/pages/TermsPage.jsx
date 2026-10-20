import { Link } from 'react-router-dom'
import PageTitle from '@/components/layout/PageTitle'
import { OPERATOR, TERMS_VERSION } from '@/legal'
import PlaceholderNotice from './PlaceholderNotice'

// The template's outline of terms of service. Each bracketed passage is for
// the app's developer to replace; raise TERMS_VERSION (here and in the
// backend) whenever the terms change.
export default function TermsPage() {
  return (
    <div className="legal-page page-column">
      <PageTitle>Terms of service</PageTitle>
      <h1>Terms of service</h1>
      <PlaceholderNotice />
      <p>Version {TERMS_VERSION}, last updated [date].</p>

      <h2>The service</h2>
      <p>
        {OPERATOR.name} provides this service. By registering, you agree to
        these terms. How we handle your personal data is explained in
        the <Link to="/privacy" className="text-link">privacy notice</Link>.
      </p>

      <h2>Who may use it</h2>
      <p>You must be at least [13, or the age your audience requires] to register.</p>

      <h2>Acceptable use</h2>
      <p>
        Do not use the service to break the law, to harm others, or to
        interfere with the service or other users&apos; accounts. [List any
        other restrictions on use.]
      </p>

      <h2>Your content</h2>
      <p>
        What you save stays yours. You give us only the rights we need to
        store it and show it to you. We may remove content, or suspend an
        account, that breaks these terms or the law; we will tell you why and
        how to contest it. [Describe how you moderate content.]
      </p>

      <h2>Reporting illegal content</h2>
      <p>
        To report content you believe is illegal, write
        to <a href={`mailto:${OPERATOR.email}`} className="text-link">{OPERATOR.email}</a> with
        where it is and why you believe it is illegal.
      </p>

      <h2>Ending your account</h2>
      <p>
        You can delete your account, and everything in it, at any time on
        your Account page. We may end accounts that break these terms.
      </p>

      <h2>Liability</h2>
      <p>[State your warranty disclaimer and limits of liability, as the law where you operate allows.]</p>

      <h2>Governing law</h2>
      <p>[Name the law that governs these terms, and where disputes are heard.]</p>

      <h2>Changes to these terms</h2>
      <p>
        We will tell you before changed terms apply, and ask you to accept
        them. [Describe how.]
      </p>
    </div>
  )
}
