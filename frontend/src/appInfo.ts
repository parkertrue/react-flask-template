// What the app says about itself, in one place for a new app to fill in.

// The app's one name: page titles and the home page use it, and tests build
// their expected text from it. index.html can't import it, and the backend
// introduces itself by it (APP_NAME in backend/app/config.py), so a test
// checks that both match.
export const APP_NAME = 'React + Flask Template'

// The home page's one-line description of the app.
export const APP_TAGLINE = 'A full-stack starter with auth, plus dev, test and production setups.'

// Who runs the app, as the contact page, the privacy notice and the terms
// name them. Placeholders: docs/personal-data.md lists what to fill in.
// public/.well-known/security.txt can't import this, so a test checks
// that its Contact matches the email.
export const OPERATOR = {
  name: '[Your name or company]',
  address: '[Street and number, postcode and city, country]',
  email: 'contact@example.com',
}

// The version of the terms that registering accepts, mirroring
// TERMS_VERSION in backend/app/auth/models.py (a test keeps them in step)
export const TERMS_VERSION = 1
