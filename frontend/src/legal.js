// Who runs the app, as the contact page, the privacy notice and the terms
// name them. Placeholders: docs/personal-data.md lists
// what to fill in. public/.well-known/security.txt can't import this, so a
// test checks that its Contact matches the email.
export const OPERATOR = {
  name: '[Your name or company]',
  address: '[Street and number, postcode and city, country]',
  email: 'contact@example.com',
}

// The version of the terms that registering accepts, mirroring
// TERMS_VERSION in backend/app/auth/models.py (a test keeps them in step)
export const TERMS_VERSION = 1
