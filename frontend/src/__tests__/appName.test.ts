import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import path from 'path'
import { APP_NAME } from '../appName'

describe('APP_NAME', () => {
  // index.html can't import it, and its title shows until React renders one
  it('is the title in index.html', () => {
    const html = readFileSync(path.resolve(import.meta.dirname, '../../index.html'), 'utf8')

    expect(/<title>(.*)<\/title>/.exec(html)?.[1]).toBe(APP_NAME)
  })
})
