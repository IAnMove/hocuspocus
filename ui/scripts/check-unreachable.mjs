#!/usr/bin/env node
// Fails when a file under ui/src is not reachable from a real entry point.
//
// Entry points are the Vite build inputs (vite.config.ts → rollupOptions.input):
// index.html → src/main.tsx, world3d-render.html and scene2d-render.html. The walk
// follows static imports and re-exports, type imports, dynamic import(), workers
// and assets (new URL('…', import.meta.url)), import.meta.glob and CSS @import.
//
// A file nothing reaches is either deleted or listed in
// scripts/unreachable-allowlist.json with a reason. A listed file that is reached
// again, or no longer exists, fails too, so the list stays honest.
import { existsSync, readdirSync, readFileSync, realpathSync, statSync } from 'node:fs'
import { dirname, extname, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const UI_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const RESOLVE_EXTENSIONS = ['.ts', '.tsx', '.mts', '.cts', '.js', '.jsx', '.mjs', '.cjs', '.json', '.css']
const SCRIPT_EXTENSIONS = new Set(['.ts', '.tsx', '.mts', '.cts', '.js', '.jsx', '.mjs', '.cjs'])
// Files under src that no entry point should import: tests, declarations and stories.
const NOT_A_MODULE = /(\.d\.ts|\.(test|spec)\.[cm]?[jt]sx?|\.stories\.[cm]?[jt]sx?)$/

const toPosix = path => path.split(sep).join('/')

/** The HTML entry points Vite builds, read from vite.config.ts. */
export function viteEntries(uiRoot = UI_ROOT) {
  const config = readFileSync(join(uiRoot, 'vite.config.ts'), 'utf8')
  const input = config.match(/input:\s*\{([^}]*)\}/)
  const pages = input ? [...input[1].matchAll(/['"]([^'"]+\.html)['"]/g)].map(match => match[1]) : []
  if (!pages.length) throw new Error('vite.config.ts: cannot read build.rollupOptions.input')
  return pages.map(page => resolve(uiRoot, page))
}

function isFile(path) {
  try {
    return statSync(path).isFile()
  } catch {
    return false
  }
}

function resolveSpecifier(uiRoot, fromFile, specifier) {
  const bare = specifier.split(/[?#]/)[0]
  if (!bare || !(bare.startsWith('.') || bare.startsWith('/'))) return null // a package, not ours
  const base = bare.startsWith('/') ? join(uiRoot, bare) : resolve(dirname(fromFile), bare)
  const stem = base.slice(0, base.length - extname(base).length)
  const candidates = [
    base,
    ...RESOLVE_EXTENSIONS.map(ext => base + ext),
    ...RESOLVE_EXTENSIONS.map(ext => join(base, `index${ext}`)),
    // TypeScript ESM style: './thing.js' names './thing.ts'.
    ...(['.js', '.jsx', '.mjs'].includes(extname(base)) ? ['.ts', '.tsx', '.mts'].map(ext => stem + ext) : []),
  ]
  return candidates.find(isFile) ?? null
}

function globToRegExp(pattern) {
  let source = ''
  for (let index = 0; index < pattern.length; index += 1) {
    const char = pattern[index]
    if (char === '*' && pattern[index + 1] === '*') {
      source += '.*'
      index += pattern[index + 2] === '/' ? 2 : 1
    } else if (char === '*') source += '[^/]*'
    else if (char === '?') source += '[^/]'
    else if (char === '{') source += '('
    else if (char === '}') source += ')'
    else if (char === ',') source += '|'
    else source += char.replace(/[.+^$()|[\]\\]/g, '\\$&')
  }
  return new RegExp(`^${source}$`)
}

function listFiles(directory) {
  if (!existsSync(directory)) return []
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    if (entry.name === 'node_modules' || entry.name === 'dist') return []
    const path = join(directory, entry.name)
    return entry.isDirectory() ? listFiles(path) : [path]
  })
}

function globMatches(uiRoot, fromFile, pattern) {
  if (pattern.startsWith('!')) return []
  const absolute = pattern.startsWith('/') ? join(uiRoot, pattern) : resolve(dirname(fromFile), pattern)
  const fixed = toPosix(absolute).split(/[*?{]/)[0]
  const root = fixed.endsWith('/') ? fixed : dirname(fixed)
  const matcher = globToRegExp(toPosix(absolute))
  return listFiles(root).filter(path => matcher.test(toPosix(path)))
}

const literal = node => (node && (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) ? node.text : null)
const isImportMeta = node => node && ts.isMetaProperty(node) && node.keywordToken === ts.SyntaxKind.ImportKeyword

/** Specifiers, glob patterns and non-literal dynamic imports in one script. */
export function scriptReferences(fileName, text) {
  const kind = /\.[cm]?tsx$|\.jsx$/.test(fileName) ? ts.ScriptKind.TSX : ts.ScriptKind.TS
  const source = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true, kind)
  const specifiers = []
  const globs = []
  const dynamic = []
  const visit = node => {
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && literal(node.moduleSpecifier)) {
      specifiers.push(literal(node.moduleSpecifier))
    } else if (ts.isImportEqualsDeclaration(node) && ts.isExternalModuleReference(node.moduleReference)) {
      specifiers.push(literal(node.moduleReference.expression))
    } else if (ts.isImportTypeNode(node) && ts.isLiteralTypeNode(node.argument)) {
      specifiers.push(literal(node.argument.literal))
    } else if (ts.isCallExpression(node)) {
      const [first] = node.arguments
      const callee = node.expression
      if (callee.kind === ts.SyntaxKind.ImportKeyword || (ts.isIdentifier(callee) && callee.text === 'require')) {
        if (literal(first)) specifiers.push(literal(first))
        else if (callee.kind === ts.SyntaxKind.ImportKeyword) dynamic.push(first ? first.getText(source) : '')
      } else if (ts.isPropertyAccessExpression(callee) && callee.name.text === 'glob' && isImportMeta(callee.expression)) {
        const patterns = first && ts.isArrayLiteralExpression(first) ? first.elements : [first]
        globs.push(...patterns.map(literal).filter(Boolean))
      }
    } else if (ts.isNewExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'URL') {
      const [target, base] = node.arguments ?? []
      const metaUrl = base && ts.isPropertyAccessExpression(base) && base.name.text === 'url' && isImportMeta(base.expression)
      if (metaUrl && literal(target)) specifiers.push(literal(target))
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  return { specifiers: specifiers.filter(Boolean), globs, dynamic }
}

function htmlReferences(fileName, text) {
  const specifiers = [
    ...[...text.matchAll(/<script\b[^>]*\bsrc=["']([^"']+)["']/gi)].map(match => match[1]),
    ...[...text.matchAll(/<link\b[^>]*\bhref=["']([^"']+)["'][^>]*>/gi)]
      .filter(match => /\brel=["'](stylesheet|modulepreload)["']/i.test(match[0]))
      .map(match => match[1]),
  ]
  const inline = [...text.matchAll(/<script\b[^>]*\btype=["']module["'][^>]*>([\s\S]*?)<\/script>/gi)]
    .map(match => scriptReferences(`${fileName}.inline.ts`, match[1]))
  return {
    specifiers: [...specifiers, ...inline.flatMap(item => item.specifiers)],
    globs: inline.flatMap(item => item.globs),
    dynamic: inline.flatMap(item => item.dynamic),
  }
}

function references(path) {
  const text = readFileSync(path, 'utf8')
  const ext = extname(path)
  if (ext === '.html') return htmlReferences(path, text)
  if (ext === '.css') {
    const specifiers = [...text.matchAll(/@import\s+(?:url\()?\s*["']([^"']+)["']/g)].map(match => match[1])
    return { specifiers, globs: [], dynamic: [] }
  }
  if (SCRIPT_EXTENSIONS.has(ext)) return scriptReferences(path, text)
  return { specifiers: [], globs: [], dynamic: [] }
}

/** Every first-party file reached from the entry points. */
export function reachableFiles(uiRoot, entries) {
  const reached = new Set()
  const dynamic = []
  const pending = [...entries]
  while (pending.length) {
    const path = pending.pop()
    if (reached.has(path)) continue
    reached.add(path)
    const found = references(path)
    for (const expression of found.dynamic) dynamic.push(`${toPosix(relative(uiRoot, path))}: import(${expression})`)
    for (const specifier of found.specifiers) {
      const target = resolveSpecifier(uiRoot, path, specifier)
      if (target && !reached.has(target)) pending.push(target)
    }
    for (const pattern of found.globs) pending.push(...globMatches(uiRoot, path, pattern).filter(item => !reached.has(item)))
  }
  return { reached, dynamic }
}

/** Files that must be reachable: everything under src (code, styles, JSON, images) except tests, declarations and stories. */
export function sourceFiles(uiRoot) {
  return listFiles(join(uiRoot, 'src')).filter(path => !NOT_A_MODULE.test(path))
}

export function readAllowlist(path) {
  const parsed = JSON.parse(readFileSync(path, 'utf8'))
  const files = parsed?.files
  if (!files || typeof files !== 'object' || Array.isArray(files)) throw new Error(`${path}: expected { "files": { path: reason } }`)
  return files
}

export function unreachableReport({ uiRoot = UI_ROOT, entries = viteEntries(uiRoot), allowlist = {} } = {}) {
  const { reached, dynamic } = reachableFiles(uiRoot, entries)
  const sources = sourceFiles(uiRoot).map(path => toPosix(relative(uiRoot, path))).sort()
  const reachedSources = new Set([...reached].map(path => toPosix(relative(uiRoot, path))))
  const unreachable = sources.filter(path => !reachedSources.has(path))
  const unlisted = unreachable.filter(path => !Object.hasOwn(allowlist, path))
  const missingReason = Object.entries(allowlist).filter(([, reason]) => !String(reason || '').trim()).map(([path]) => path)
  const stale = Object.keys(allowlist).filter(path => !unreachable.includes(path)).sort()
  return { sources: sources.length, unreachable, unlisted, stale, missingReason, dynamic }
}

function main() {
  const allowlistPath = join(UI_ROOT, 'scripts', 'unreachable-allowlist.json')
  const report = unreachableReport({ allowlist: readAllowlist(allowlistPath) })
  for (const item of report.dynamic) console.warn(`warning: dynamic import the walk cannot follow: ${item}`)
  const problems = [
    ...report.unlisted.map(path => `${path}: no entry point reaches it. Import it from the app, delete it, or list it with a reason in scripts/unreachable-allowlist.json.`),
    ...report.stale.map(path => `${path}: listed in scripts/unreachable-allowlist.json but reached or gone. Remove the entry.`),
    ...report.missingReason.map(path => `${path}: listed without a reason.`),
  ]
  if (problems.length) {
    console.error(`Unreachable UI files: ${problems.length} problem(s)`)
    for (const problem of problems) console.error(`- ${problem}`)
    process.exit(1)
  }
  console.log(
    `Unreachable UI files: ${report.sources - report.unreachable.length}/${report.sources} src files reached; `
    + `${report.unreachable.length} listed in scripts/unreachable-allowlist.json.`,
  )
}

/** True when node runs this file, also through a symlinked path or another drive-letter case on Windows. */
export function invokedDirectly(argvPath = process.argv[1], moduleUrl = import.meta.url) {
  if (!argvPath) return false
  try {
    const invoked = realpathSync(resolve(argvPath))
    const module = realpathSync(fileURLToPath(moduleUrl))
    return process.platform === 'win32' ? invoked.toLowerCase() === module.toLowerCase() : invoked === module
  } catch {
    return false
  }
}

if (invokedDirectly()) main()
