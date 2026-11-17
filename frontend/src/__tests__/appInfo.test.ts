import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync } from 'fs'
import path from 'path'
import { APP_NAME, OPERATOR, TERMS_VERSION } from '../appInfo'
import { BACKEND_APP, backendConstant, backendString } from '@/test/backend'
import { slugify } from '@/utils/download'

const securityTxt = readFileSync(
  path.resolve(import.meta.dirname, '../../public/.well-known/security.txt'), 'utf8')
const field = (name: string) => new RegExp(`^${name}: (.*)$`, 'm').exec(securityTxt)?.[1] ?? ''

const ROOT = path.resolve(BACKEND_APP, '../..')

// Every source and test file under a folder of the repository, by its path
// from the root, skipping caches
function sourceFiles(dir: string): string[] {
  return readdirSync(path.join(ROOT, dir), { recursive: true, encoding: 'utf8' })
    .filter(file => /\.(tsx?|py)$/.test(file) && !file.includes('__pycache__'))
    .map(file => path.posix.join(dir, file.replaceAll(path.sep, '/')))
}

describe("the app's name", () => {
  // index.html can't import it, and its title shows until React renders one
  it('is the title in index.html', () => {
    const html = readFileSync(path.join(ROOT, 'frontend/index.html'), 'utf8')

    expect(/<title>(.*)<\/title>/.exec(html)?.[1]).toBe(APP_NAME)
  })

  it('is the name the backend introduces itself by', () => {
    expect(backendString('config.py', 'APP_NAME')).toBe(APP_NAME)
  })

  // So renaming the app is three edits, and a test catches a missed one:
  // here, index.html and the backend's config.py
  it('is written nowhere else in the code or its tests', () => {
    const holders = ['frontend/src/appInfo.ts', 'backend/app/config.py']
    const written = ['frontend/src', 'frontend/e2e', 'backend/app', 'backend/tests']
      .flatMap(sourceFiles)
      .filter(file => !holders.includes(file))
      .filter(file => {
        const source = readFileSync(path.join(ROOT, file), 'utf8')
        return source.includes(APP_NAME) || source.includes(slugify(APP_NAME))
      })

    expect(written).toEqual([])
  })
})

describe('legal details', () => {
  it('accept the terms version the backend requires', () => {
    expect(TERMS_VERSION).toBe(backendConstant('auth/models.py', 'TERMS_VERSION'))
  })

  // security.txt can't import appInfo.ts
  it('give security.txt the operator\'s contact email', () => {
    expect(field('Contact')).toBe(`mailto:${OPERATOR.email}`)
  })

  // RFC 9116 wants Expires less than a year away, and a lapsed file is one
  // reporters should ignore. This starts failing 30 days before it lapses,
  // the template's own CI included, so someone renews it in time
  it('give security.txt an expiry date, at least 30 days and at most a year away', () => {
    expect(field('Expires')).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/)
    const daysLeft = (Date.parse(field('Expires')) - Date.now()) / 86_400_000
    expect(daysLeft).toBeGreaterThan(30)
    expect(daysLeft).toBeLessThanOrEqual(366)
  })
})
