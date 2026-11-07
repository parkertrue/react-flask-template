import { configDefaults, defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { readdirSync } from 'fs'
import path from 'path'

const floor = { statements: 95, branches: 95, functions: 95, lines: 95 }
const foldersIn = (folder: string) =>
  readdirSync(path.join(import.meta.dirname, folder), { withFileTypes: true })
    .filter(entry => entry.isDirectory() && entry.name !== '__tests__')
    .map(entry => `${folder}/${entry.name}/**`)
// Every folder of src/ and each feature on its own, plus the root files, so
// a new folder gets a floor without being listed. src/test is excluded
// from coverage below.
const coveredGlobs = [
  ...foldersIn('src').filter(glob => !['src/features/**', 'src/test/**'].includes(glob)),
  ...foldersIn('src/features'),
  'src/*.{ts,tsx}',
]

export default defineConfig({
  plugins: [react()],
  // `@/x` is src/x, so an import survives its file moving. tsconfig.base.json
  // maps the same path for the type check and the editor.
  resolve: {
    alias: { '@': path.join(import.meta.dirname, 'src') }
  },
  // The bundle is a copy of every library in it, and their licenses (MIT
  // for all of them today) require their notices to travel with it. This
  // writes them to a file nginx serves beside index.html.
  build: {
    license: { fileName: 'third-party-licenses.txt' },
  },
  server: {
    // localhost only: the dev server proxies to Flask in debug mode, whose
    // tracebacks should not be reachable from the LAN. Opt in to LAN access
    // with `npm run dev -- --host`.
    host: 'localhost',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      }
    }
  },
  test: {
    environment: 'jsdom',
    // The page's URL. src/test/setup.ts stubs window.location with the same
    // origin, and MSW resolves relative handler paths against it, so the two
    // must agree for handlers to match the requests axios sends.
    environmentOptions: { jsdom: { url: 'http://localhost/' } },
    setupFiles: './src/test/setup.ts',
    // Before each test, every mock loses the return values and
    // implementations an earlier test gave it, so no test depends on
    // another having run first. Stubbed globals are put back too.
    mockReset: true,
    unstubGlobals: true,
    // A new order every run, so a test leaning on another's leftovers fails
    // at once. Replay a failing order with --sequence.seed=<seed>.
    sequence: { shuffle: true },
    // Playwright runs e2e/, not Vitest
    exclude: [...configDefaults.exclude, '**/e2e/**'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      // Without include, a file no test imports is left out of the report
      // rather than counted as 0%, so an untested new file goes unnoticed.
      include: ['src/**/*.{ts,tsx}'],
      // The same floor per folder too, so a new feature's gaps can't hide
      // behind well-covered code elsewhere in the total
      thresholds: {
        ...floor,
        ...Object.fromEntries(coveredGlobs.map(glob => [glob, floor])),
      },
      // Test files are left out automatically; a feature's own fixtures in
      // __tests__ would pad its floor
      exclude: ['src/test/**', 'src/**/__tests__/**', 'src/main.tsx']
    },
  }
})
