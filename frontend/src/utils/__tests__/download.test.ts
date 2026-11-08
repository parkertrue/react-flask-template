import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { OBJECT_URL_LIFETIME_MS, saveJsonFile, slugify } from '../download'

describe('slugify', () => {
  it.each([
    ['React + Flask Template', 'react-flask-template'],
    ['  Notes!  ', 'notes'],
    ['Plan B 2', 'plan-b-2'],
  ])('turns %j into %j', (text, slug) => {
    expect(slugify(text)).toBe(slug)
  })
})

// jsdom has no object URLs and does not download, so both are stood in for
const createObjectURL = vi.fn<(blob: Blob) => string>()
const revokeObjectURL = vi.fn<(url: string) => void>()

describe('saveJsonFile', () => {
  let clicked: { href: string; download: string }[]

  beforeEach(() => {
    vi.useFakeTimers()
    createObjectURL.mockReturnValue('blob:saved')
    Object.assign(URL, { createObjectURL, revokeObjectURL })
    clicked = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push({ href: this.href, download: this.download })
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('downloads the value as pretty-printed JSON under the file name', async () => {
    saveJsonFile('export.json', { a: [1, 'two'] })

    expect(clicked).toEqual([{ href: 'blob:saved', download: 'export.json' }])
    const blob = createObjectURL.mock.calls[0]?.[0]
    expect(blob?.type).toBe('application/json')
    expect(await blob?.text()).toBe('{\n  "a": [\n    1,\n    "two"\n  ]\n}')
  })

  it('frees the file once the download has had time to read it', () => {
    saveJsonFile('export.json', {})

    vi.advanceTimersByTime(OBJECT_URL_LIFETIME_MS - 1)
    expect(revokeObjectURL).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:saved')
  })
})
