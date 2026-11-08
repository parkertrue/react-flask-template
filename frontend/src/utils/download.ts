// How long a saved file's object URL outlives the click. The download reads
// it after the click returns, so it can't be revoked at once; a minute is
// ample, and frees the copy after.
export const OBJECT_URL_LIFETIME_MS = 60_000

// Text made safe for a file name: lowercase letters and digits, every other
// run of characters one dash, none at either end
export function slugify(text: string) {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
}

// Saves value as a pretty-printed JSON file through the browser's own
// download. For data already fetched: a request that needs the access token
// cannot be a plain link.
export function saveJsonFile(filename: string, value: unknown) {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  setTimeout(() => { URL.revokeObjectURL(url) }, OBJECT_URL_LIFETIME_MS)
}
