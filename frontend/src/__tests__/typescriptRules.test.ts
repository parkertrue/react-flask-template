import { beforeAll, describe, it, expect } from 'vitest'
import path from 'path'
import ts from 'typescript'

// The type check is config too, and a loosened tsconfig fails silently:
// every file still passes, just with less checked. These plant code in
// made-up files of each project and type-check them with the real
// tsconfig, as check_lint_rules.py does for mypy.
const FRONTEND = path.resolve(import.meta.dirname, '../..')

const PROJECTS = {
  app: { config: 'tsconfig.app.json', dir: 'src/utils' },
  test: { config: 'tsconfig.test.json', dir: 'src/utils/__tests__' },
  node: { config: 'tsconfig.node.json', dir: 'e2e' },
}
type Project = keyof typeof PROJECTS

// Project, what is planted, the code, and the error tsc must report (none:
// code the project must accept)
const CASES: [Project, string, string, number | null][] = [
  // strict, in each project
  ['app', 'an untyped parameter', 'export const f = (x) => x', 7006],
  ['test', 'an untyped parameter', 'export const f = (x) => x', 7006],
  ['node', 'an untyped parameter', 'export const f = (x) => x', 7006],
  ['app', 'null where none is allowed', 'export const s: string = null', 2322],
  // The checks strict leaves out
  ['app', 'an index that may be out of range', 'const a: string[] = []\nexport const s: string = a[0]', 2322],
  ['app', 'a path that returns nothing', 'export function f(x: boolean) { if (x) return 1 }', 7030],
  ['app', 'a case that falls through', 'export function f(x: number) { switch (x) { case 1: f(2)\n case 2: return } }', 7029],
  ['app', 'an override not marked', 'class A { m() {} }\nexport class B extends A { m() {} }', 4114],
  ['app', 'syntax with no JavaScript twin', 'export enum E { A }', 1294],
  ['app', 'a type imported as a value', "import { Account } from '@/auth/authService'\nexport const a: Account | null = null", 1484],
  // App code runs in the browser alone; tests and tooling run under Node
  ['app', 'a Node global', 'export const env = process.env', 2591],
  ['app', 'a Node module', "import { readFileSync } from 'fs'\nexport const r = readFileSync", 2591],
  ['test', 'Node', "import { readFileSync } from 'fs'\nexport const r = readFileSync(process.cwd())", null],
  ['node', 'Node', "import { readFileSync } from 'fs'\nexport const r = readFileSync(process.cwd())", null],
]

/** The error codes tsc reports for each of `codes`, planted in `project` */
function typeCheck(project: Project, codes: string[]) {
  const { config, dir } = PROJECTS[project]
  const parsed = ts.getParsedCommandLineOfConfigFile(
    path.join(FRONTEND, config), {}, { ...ts.sys, onUnRecoverableConfigFileDiagnostic: () => {} })
  if (!parsed) throw new Error(`${config} does not parse`)
  const planted = new Map(codes.map((code, index) => [path.join(FRONTEND, dir, `planted${index}.ts`), code]))

  const host = ts.createCompilerHost(parsed.options)
  const getSourceFile = host.getSourceFile.bind(host)
  const fileExists = host.fileExists.bind(host)
  host.getSourceFile = (fileName, languageVersion, ...rest) => {
    const code = planted.get(path.resolve(fileName))
    return code === undefined
      ? getSourceFile(fileName, languageVersion, ...rest)
      : ts.createSourceFile(fileName, code, languageVersion)
  }
  host.fileExists = fileName => planted.has(path.resolve(fileName)) || fileExists(fileName)

  const program = ts.createProgram([...planted.keys()], parsed.options, host)
  return [...planted.keys()].map(fileName => {
    const source = program.getSourceFile(fileName)
    return [...program.getSyntacticDiagnostics(source), ...program.getSemanticDiagnostics(source)]
      .map(diagnostic => diagnostic.code)
  })
}

// Each case's errors, by its name; one program per project, which is fast
const reported = new Map<string, number[]>()
const nameOf = (project: Project, what: string) => `${project}: ${what}`

beforeAll(() => {
  for (const project of Object.keys(PROJECTS) as Project[]) {
    const cases = CASES.filter(([p]) => p === project)
    typeCheck(project, cases.map(([, , code]) => code))
      .forEach((errors, index) => {
        const [, what] = cases[index] ?? []
        reported.set(nameOf(project, what ?? ''), errors)
      })
  }
}, 60_000)

describe('the type check', () => {
  it.each(CASES.filter(([, , , error]) => error !== null))('refuses, in %s code, %s', (project, what, _, error) => {
    expect(reported.get(nameOf(project, what))).toContain(error)
  })

  it.each(CASES.filter(([, , , error]) => error === null))('lets %s code use %s', (project, what) => {
    expect(reported.get(nameOf(project, what))).toEqual([])
  })
})
