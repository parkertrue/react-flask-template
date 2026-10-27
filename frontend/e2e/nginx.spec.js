import { execFileSync } from 'child_process'
import { readFileSync } from 'fs'
import path from 'path'
import { test, expect } from '@playwright/test'
import { SERVICE_UNAVAILABLE_MESSAGE } from './helpers'

// What nginx itself promises (nginx/servers/tls.conf.template, app_server.conf), checked
// over the wire. The app works the same without any of these, so only this
// file notices one breaking.

const HTTP = 'http://localhost:8080'

const REPO_ROOT = path.resolve(import.meta.dirname, '../..')

// Runs docker compose against the test stack Playwright brought up, and
// returns what it printed
function testStack(...args) {
  return execFileSync('docker', [
    'compose', '--env-file', '.env.test', '-f', 'docker-compose.test.yml', '--profile', 'e2e', ...args,
  ], { cwd: REPO_ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] })
}

// The lines a service has logged, newest last
function logLines(service) {
  return testStack('logs', '--no-log-prefix', service).split('\n')
}

// Polls a service's log for the line `matches` picks, and returns it parsed
async function loggedLine(service, matches) {
  let line
  await expect.poll(() => {
    line = logLines(service).find(matches)
    return line !== undefined
  }).toBe(true)
  return JSON.parse(line)
}

// The backend container's address on the test stack's network
function backendAddress() {
  const id = testStack('ps', '--quiet', 'backend').trim()
  return execFileSync('docker', [
    'inspect', '--format', '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}', id,
  ], { encoding: 'utf8' }).trim()
}

// Whether the backend answers its health check from inside its own container,
// bypassing nginx
function backendServes() {
  try {
    testStack('exec', '-T', 'backend', 'python', '-c',
      "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=1)")
    return true
  } catch {
    return false
  }
}

// Waits until a rate-limit zone's bucket is empty. A flood ends once one
// request gets through, which leaves the bucket holding up to its burst; it
// drains at the zone's rate (nginx/Dockerfile, which the test stack keeps
// for these zones), so burst / rate seconds later it holds nothing.
async function waitForEmptyBucket(zone) {
  const read = file => readFileSync(path.join(REPO_ROOT, 'nginx', file), 'utf8')
  const rate = Number(read('Dockerfile').match(new RegExp(`NGINX_${zone.toUpperCase()}_RATE=(\\d+)r/s`))[1])
  const burst = Number(read('app_server.conf').match(new RegExp(`zone=${zone} burst=(\\d+)`))[1])
  await new Promise(resolve => setTimeout(resolve, burst / rate * 1000))
}

const SECURITY_HEADERS = {
  'strict-transport-security': /max-age=\d+/,
  'x-frame-options': /^DENY$/,
  'x-content-type-options': /^nosniff$/,
  'referrer-policy': /^strict-origin-when-cross-origin$/,
  'content-security-policy': /frame-ancestors 'none'/,
}

async function firstAssetPath(request) {
  const html = await (await request.get('/')).text()
  return html.match(/\/assets\/[^"']+\.js/)[0]
}

test.describe('nginx', () => {
  test('every kind of response carries the security headers', async ({ request }) => {
    const paths = ['/', '/api/health', '/api/account', '/favicon.ico', await firstAssetPath(request)]

    for (const path of paths) {
      const headers = (await request.get(path)).headers()
      for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
        expect(headers[name], `${name} on ${path}`).toMatch(value)
      }
    }
  })

  test('HTML is revalidated, hashed assets are cached for good', async ({ request }) => {
    const page = await request.get('/account')
    const asset = await request.get(await firstAssetPath(request))

    expect(page.headers()['cache-control']).toBe('no-cache')
    // Exact: nginx's expires would add a second Cache-Control header
    expect(asset.headers()['cache-control']).toBe('public, max-age=31536000, immutable')
  })

  test('the bundled libraries\' license notices are served as text', async ({ request }) => {
    // Written by the build (vite.config.js); without it the SPA fallback
    // would answer this path with index.html
    const response = await request.get('/third-party-licenses.txt')

    expect(response.status()).toBe(200)
    expect(response.headers()['content-type']).toBe('text/plain')
    expect(await response.text()).toContain('## react - ')
  })

  test('security.txt is served as text, with a contact and an expiry', async ({ request }) => {
    // From public/; without it the SPA fallback would answer with index.html
    const response = await request.get('/.well-known/security.txt')

    expect(response.status()).toBe(200)
    expect(response.headers()['content-type']).toBe('text/plain')
    const text = await response.text()
    expect(text).toMatch(/^Contact: mailto:/m)
    expect(text).toMatch(/^Expires: /m)
  })

  test('API responses are never stored', async ({ request }) => {
    // Set by Flask; nginx must pass it through untouched
    for (const path of ['/api/health', '/api/account']) {
      const response = await request.get(path)
      expect(response.headers()['cache-control'], path).toBe('no-store')
    }
  })

  test('plain HTTP redirects to HTTPS', async ({ request }) => {
    const response = await request.get(`${HTTP}/account?x=1`, { maxRedirects: 0 })

    expect(response.status()).toBe(301)
    expect(response.headers()['location']).toBe('https://localhost/account?x=1')
  })

  test('a request for another host gets no answer', async ({ request }) => {
    // The catch-all server: a bare IP, or any Host but the configured one
    await expect(request.get('http://127.0.0.1:8080/')).rejects.toThrow()
    await expect(request.get('https://127.0.0.1:8443/')).rejects.toThrow()
  })

  test('API paths are proxied whatever their extension', async ({ request }) => {
    // Not served from disk: a static-file rule must never outrank /api
    const response = await request.get('/api/avatar.png')

    expect(response.status()).toBe(404)
    expect(await response.json()).toEqual(
      { error: { code: 'NOT_FOUND', message: 'Resource not found' } })
  })

  test('a burst past the rate limit is refused in the API\'s error shape, and barely logged', async ({ request }) => {
    // The user agent finds this burst's access lines; the query string must
    // reach no line at all, error log included
    const userAgent = `burst-${Date.now()}`
    const secret = `secret-${Date.now()}`
    // 30 r/s with a burst of 20 (nginx/Dockerfile): 60 at once overflows it
    const responses = await Promise.all(Array.from({ length: 60 }, () =>
      request.get(`/api/account?token=${secret}`, { headers: { 'User-Agent': userAgent } })))
    const limited = responses.filter(response => response.status() === 429)

    // The first requests reach Flask, which refuses them for want of a token
    expect(new Set(responses.map(response => response.status()))).toEqual(new Set([401, 429]))
    for (const response of limited) {
      expect(await response.json()).toEqual({
        error: { code: 'RATE_LIMITED', message: 'Too many requests, please try again later' },
      })
    }

    // Every request served is logged; of the refused, one in 100 (nginx.conf),
    // so 10 of about 40 would take odds of 1 in 10^11
    const served = responses.length - limited.length
    const burstLines = () => logLines('nginx').filter(l => l.includes(userAgent)).map(l => JSON.parse(l))
    await expect.poll(() => burstLines().filter(line => line.status === 401).length).toBe(served)
    expect(burstLines().filter(line => line.status === 429).length).toBeLessThan(10)
    expect(logLines('nginx').filter(l => l.includes(secret))).toEqual([])

    // Let the bucket empty, so the tests after this one are not limited
    await expect.poll(async () => (await request.get('/api/account')).status()).toBe(401)
    await waitForEmptyBucket('api')
  })

  test('an oversized body is refused in the API\'s error shape', async ({ request }) => {
    const response = await request.post('/api/auth/login', {
      data: { email: 'a@example.com', password: 'x'.repeat(20 * 1024) },
    })

    expect(response.status()).toBe(413)
    expect((await response.json()).error.code).toBe('PAYLOAD_TOO_LARGE')
    // nginx answers this itself, from a location of its own
    expect(response.headers()['content-security-policy']).toBe("default-src 'none'; frame-ancestors 'none'")
  })

  test('the app\'s icon is served, and /favicon.ico is not the page', async ({ request }) => {
    const icon = await request.get('/favicon.svg')
    const ico = await request.get('/favicon.ico')

    expect(icon.status()).toBe(200)
    expect(icon.headers()['content-type']).toBe('image/svg+xml')
    // Without its own location, the SPA fallback would answer with index.html
    expect(ico.status()).toBe(404)
    expect(await ico.text()).not.toContain('<div id="root">')
  })

  test('each request is logged as one JSON line, without its query string', async ({ request }) => {
    // A path of its own finds this request's line among the others; the
    // quotes in the user agent would break a line nginx did not escape
    const route = `/api/no-such-route-${Date.now()}`
    await request.get(`${route}?token=secret-in-a-link`, { headers: { 'User-Agent': 'probe "quoted"' } })

    const line = await loggedLine('nginx', l => l.includes(route))

    expect(line).toMatchObject({
      time: expect.stringMatching(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$/),
      request_id: expect.stringMatching(/^[0-9a-f]{32}$/),
      method: 'GET',
      // A reset or verification link's token must not stay in the log
      path: route,
      status: 404,
      user_agent: 'probe "quoted"',
      request_time: expect.any(Number),
      // The backend answered, so nginx timed it
      upstream_response_time: expect.stringMatching(/^\d+\.\d{3}$/),
    })
    expect(JSON.stringify(line)).not.toContain('secret-in-a-link')
  })

  test('the client\'s own text is cut short in the log', async ({ request }) => {
    // Headers of 8 KB, as much as nginx accepts, would make lines that roll
    // the log over in seconds. (A path that long gunicorn refuses: 4 KB.)
    const route = `/api/no-such-route-${Date.now()}`
    const long = 'x'.repeat(8000)
    await request.get(route + long.slice(0, 2000), { headers: { 'User-Agent': long, 'Referer': long } })

    const line = await loggedLine('nginx', l => l.includes(route))

    expect(line.path).toBe((route + long).slice(0, 512))
    expect(line.user_agent).toBe(long.slice(0, 256))
    expect(line.referer).toBe(long.slice(0, 256))
  })

  test('a backend line names the request it was logged during', async ({ request }) => {
    // A wrong password is logged by both: nginx's access line and the
    // backend's login_failed event. The user agent finds nginx's.
    const userAgent = `probe-${Date.now()}`
    await request.post('/api/auth/login', {
      data: { email: `${userAgent}@example.com`, password: 'WrongPass123' },
      headers: { 'User-Agent': userAgent },
    })

    const access = await loggedLine('nginx', l => l.includes(userAgent))
    const event = await loggedLine('backend', l => l.includes(access.request_id))

    expect(access.status).toBe(401)
    expect(event).toMatchObject({ logger: 'app.security', message: 'login_failed' })
  })

  test('a page whose path only starts with "api" is the app', async ({ request }) => {
    const response = await request.get('/apidocs')

    expect(response.status()).toBe(200)
    expect(await response.text()).toContain('<div id="root">')
  })

  test('a client loading pages in a loop is refused in the API\'s error shape', async ({ request }) => {
    // 10 r/s with a burst of 20 (nginx/Dockerfile): 60 at once overflows it
    const responses = await Promise.all(
      Array.from({ length: 60 }, () => request.get('/account')))
    const limited = responses.filter(response => response.status() === 429)

    expect(new Set(responses.map(response => response.status()))).toEqual(new Set([200, 429]))
    for (const response of limited) {
      expect(await response.json()).toEqual({
        error: { code: 'RATE_LIMITED', message: 'Too many requests, please try again later' },
      })
    }

    // Let the bucket empty, so the tests after this one are not limited
    await expect.poll(async () => (await request.get('/account')).status()).toBe(200)
    await waitForEmptyBucket('page')
  })
})

test.describe('nginx while the backend is away', () => {
  test.describe.configure({ timeout: 180_000 })

  // Whatever a test leaves behind, the next spec finds the backend running
  test.afterAll(() => testStack('up', '-d', '--wait', '--no-deps', 'backend'))

  test('a stopped backend answers at once, in the API\'s error shape', async ({ request }) => {
    testStack('stop', 'backend')

    // Nothing answers at the backend's fixed address, so each request waits
    // out proxy_connect_timeout and gets a 504. Now and then one fails
    // sooner as unreachable, a 502 from the same error page: poll for the 504.
    const durations = []
    let last
    await expect.poll(async () => {
      const started = Date.now()
      last = await request.get('/api/health')
      durations.push(Date.now() - started)
      return last.status()
    }, { intervals: [500], timeout: 30_000 }).toBe(504)

    // The 2s connect timeout (proxy_params.conf), not a long hang
    expect(Math.max(...durations)).toBeLessThan(3000)
    expect(last.headers()['content-type']).toBe('application/json')
    // An outage, in the backend's own words: not "Something went wrong"
    expect(await last.json()).toEqual(
      { error: { code: 'SERVICE_UNAVAILABLE', message: SERVICE_UNAVAILABLE_MESSAGE } })
  })

  test('a replaced backend is reached as soon as it serves', async ({ request }) => {
    // From a running backend that nginx reaches, as before a deploy
    testStack('up', '-d', '--wait', '--no-deps', 'backend')
    await expect.poll(async () => (await request.get('/api/health')).status(),
      { intervals: [200], timeout: 30_000 }).toBe(200)

    // A deploy's swap, with a gap in which no backend container exists. Had
    // nginx looked the backend up by name, Docker's DNS could answer it with
    // "not found" or a server failure, either of which leaves a healthy new
    // backend unreachable for up to about 30s.
    const before = backendAddress()
    testStack('rm', '--stop', '--force', 'backend')
    await new Promise(resolve => setTimeout(resolve, 5000))
    testStack('up', '-d', '--no-deps', 'backend')
    await expect.poll(backendServes, { intervals: [100], timeout: 60_000 }).toBe(true)

    // The address nginx connects to (templates/00-upstream.conf.template),
    // not a name: whether a lookup fails mid-swap is up to Docker's DNS, so
    // a swap alone would catch a lookup by name only now and then
    expect(backendAddress()).toBe(before)
    const upstream = testStack('exec', '-T', 'nginx', 'nginx', '-T').match(/upstream backend \{[^}]*\}/)[0]
    expect(upstream).toContain(`server ${before}:5000;`)
    const started = Date.now()
    await expect.poll(async () => (await request.get('/api/health')).status(),
      { intervals: [100], timeout: 30_000 }).toBe(200)
    expect(Date.now() - started).toBeLessThan(1000)
  })
})
