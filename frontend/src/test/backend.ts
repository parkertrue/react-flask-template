import { readFileSync } from 'fs'
import path from 'path'

// The backend's source, for tests that keep the frontend's copy of one of
// its values in step with the original
export const BACKEND_APP = path.resolve(import.meta.dirname, '../../../backend/app')

/** The integer a backend module assigns at top level (`NAME = 123`) */
export function backendConstant(file: string, name: string) {
  const source = readFileSync(path.join(BACKEND_APP, file), 'utf8')
  const match = new RegExp(`^${name} = (\\d+)$`, 'm').exec(source)
  if (!match) throw new Error(`${file} assigns no ${name}`)
  return Number(match[1])
}
