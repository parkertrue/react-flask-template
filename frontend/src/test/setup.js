import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'

// React warns when state changes outside act(): the test asserted, or ended,
// before the component settled, which is how flaky tests start. Fail the
// test instead; await the final state (findBy*, waitFor) to fix it.
const consoleError = console.error
let actWarning = null
console.error = (...args) => {
  if (typeof args[0] === 'string' && args[0].includes('not wrapped in act')) {
    actWarning ??= args[0].replace('%s', args[1])
  }
  consoleError(...args)
}

afterEach(() => {
  cleanup()
  localStorage.clear()

  const warning = actWarning
  actWarning = null
  if (warning) {
    throw new Error(`State updated outside act(): ${warning.split('\n')[0]}`)
  }
})

// jsdom has <dialog> but none of its methods. This stands in for the part
// the dialogs use: open, close with a return value (firing "close"), and
// Escape, which fires "cancel" and then closes. Playwright runs the real one.
HTMLDialogElement.prototype.showModal = function () {
  this.returnValue = ''
  this.open = true
}
HTMLDialogElement.prototype.close = function (returnValue) {
  if (!this.open) return
  if (returnValue !== undefined) this.returnValue = returnValue
  this.open = false
  this.dispatchEvent(new Event('close'))
}
document.addEventListener('keydown', (e) => {
  const dialog = document.querySelector('dialog[open]')
  if (e.key === 'Escape' && dialog?.dispatchEvent(new Event('cancel', { cancelable: true }))) {
    dialog.close()
  }
})

// React Router's <ScrollRestoration> scrolls on every navigation, which jsdom
// does not implement; unstubbed, each one logs a warning that buries real ones
window.scrollTo = () => {}

// A plain object, so a test can see a full-page redirect (location.href = ...),
// which the app must never use to end a session; jsdom does not navigate.
// The origin matches vite.config.js's jsdom url.
Object.defineProperty(window, 'location', {
  writable: true,
  value: {
    href: 'http://localhost/',
    origin: 'http://localhost',
    protocol: 'http:',
    host: 'localhost',
    hostname: 'localhost',
    port: '',
  },
})
