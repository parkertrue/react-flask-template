import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import PageTitle from '../PageTitle'
import { APP_NAME } from '@/appName'

describe('PageTitle', () => {
  it.each([
    ['names the page, then the app', 'Login', `Login | ${APP_NAME}`],
    ['is just the app name without a page name', undefined, APP_NAME],
  ])('%s', (_, name, title) => {
    render(<PageTitle>{name}</PageTitle>)

    expect(document.title).toBe(title)
  })
})
