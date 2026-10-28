import { Link } from 'react-router-dom'
import PageTitle from '@/components/layout/PageTitle'
import { OPERATOR } from '@/legal'
import PlaceholderNotice from './PlaceholderNotice'

// The template's outline of a privacy notice, seeded from the data the
// template itself keeps (docs/personal-data.md). Each
// bracketed passage is for the app's developer to replace.
export default function PrivacyPage() {
  return (
    <div className="legal-page page-column">
      <PageTitle>Privacy notice</PageTitle>
      <h1>Privacy notice</h1>
      <PlaceholderNotice />

      <h2>Who we are</h2>
      <p>
        {OPERATOR.name} runs this service and decides how your personal data
        is used. You can reach us at <a href={`mailto:${OPERATOR.email}`} className="text-link">{OPERATOR.email}</a>,
        or by the other ways on the <Link to="/contact" className="text-link">contact page</Link>.
        [Your data protection officer or EU/UK representative, if you need one.]
      </p>

      <h2>What we collect</h2>
      <ul>
        <li>Your account: your email address, a hash of your password (never the password itself) and when you registered.</li>
        <li>Which version of the terms you accepted, and when.</li>
        <li>What you save in the app. [List each kind of content your app stores.]</li>
        <li>Security records: your IP address, browser, the pages and requests you make, and sign-in events such as failed logins, kept to protect your account and the service.</li>
        <li>In your browser: a sign-in cookie and a few values in local storage that keep you signed in. They are strictly necessary for the service you asked for, so we do not ask for consent to them, and we use no analytics or advertising cookies.</li>
      </ul>
      <p>
        You need to give your email address and a password to register;
        without them we cannot create an account. [If the CCPA applies: the
        categories of sources of this data.]
      </p>

      <h2>Why, and on what legal basis</h2>
      <p>
        We use your account and content to provide the service you signed up
        for (performance of a contract). We keep security records because we
        have a legitimate interest in protecting accounts and the service.
        [No decision about you is made by automated means alone.] [Check
        these bases, and add any other purpose your app has.]
      </p>

      <h2>How long we keep it</h2>
      <p>
        We keep your account and content until you delete them.
        Security records are kept for [period, for example 6 months]. [State
        how long backups keep deleted data.]
      </p>

      <h2>Who else processes it</h2>
      <p>
        [Name each provider that handles personal data for you, such as your
        hosting provider or a log service, and the country it processes data
        in, with the safeguard for any transfer outside the EU/UK.] We do not
        sell your personal data or share it for advertising.
      </p>

      <h2>Your rights</h2>
      <p>
        You can delete your account, and everything in it, on your Account
        page. You can also ask us for a copy of your data, in a
        machine-readable form you can take elsewhere (portability); to
        correct it; or to restrict or object to how we use it. Write to us
        at <a href={`mailto:${OPERATOR.email}`} className="text-link">{OPERATOR.email}</a> from the
        email address of your account. We answer within one month. [If the
        CCPA applies: we will not discriminate against you for using your
        rights.]
      </p>

      <h2>Complaints</h2>
      <p>
        You can complain to a data protection authority, such as the one where
        you live. [Name your lead supervisory authority, if you have one.]
      </p>

      <h2>Do Not Track</h2>
      <p>
        We do not track you across other sites, so there is nothing for a Do
        Not Track signal to switch off.
      </p>

      <h2>Children</h2>
      <p>
        The service is not meant for children under [13, or the age your
        audience requires], and we do not knowingly collect their data.
      </p>

      <h2>Changes to this notice</h2>
      <p>Last updated [date]. We will tell you about important changes before they apply.</p>
    </div>
  )
}
