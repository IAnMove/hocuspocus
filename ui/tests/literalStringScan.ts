import { readdirSync, readFileSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * Hardcoded user-visible strings under `ui/src`.
 *
 * Counts JSX text that contains a letter, the same strings when they are a
 * JSX child expression, and string literals passed to `title`, `placeholder`,
 * `aria-label`, `alt` or `label` (including `||`, `??`, `&&` and ternary
 * branches, not the condition). Also counts object-literal properties named
 * `label`, `title`, `description`, `placeholder`, `tooltip`, `hint` or `name`
 * in `.ts` and `.tsx` (not tests). Skips `t(...)`, `tStudio`-style helpers,
 * `translate`, URLs, and a line marked `// i18n-ok: reason`.
 */
const uiRoot = fileURLToPath(new URL('..', import.meta.url))
const require = createRequire(join(uiRoot, 'package.json'))
const ts = require('typescript') as typeof import('typescript')

const JSX_ATTRS = new Set(['title', 'placeholder', 'aria-label', 'alt', 'label'])
const CATALOG_KEYS = new Set(['label', 'title', 'description', 'placeholder', 'tooltip', 'hint', 'name'])
const SKIP_DIRS = new Set(['node_modules', 'dist', 'tests', '__tests__'])

type SourceFile = import('typescript').SourceFile
type Expression = import('typescript').Expression
type Node = import('typescript').Node

function isScannedFile(name: string) {
  if (name.endsWith('.d.ts') || /\.(test|spec)\.tsx?$/.test(name)) return false
  return name.endsWith('.ts') || name.endsWith('.tsx')
}

function walkSources(dir: string, out: string[]) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) {
      if (!SKIP_DIRS.has(name)) walkSources(path, out)
      continue
    }
    if (isScannedFile(name)) out.push(path)
  }
}

/** Every `.ts` / `.tsx` file under `ui/src`, including Video 3D and the workbench. */
export function literalSourceRelPaths() {
  const absolute: string[] = []
  walkSources(join(uiRoot, 'src'), absolute)
  return absolute.map(path => relative(uiRoot, path).split('\\').join('/')).sort()
}

function hasLetter(value: string) {
  const visible = value.replace(/&(?:#x[0-9a-fA-F]+|#\d+|[a-zA-Z]+);/g, '')
  return /\p{L}/u.test(visible)
}

function isUrl(value: string) {
  const trimmed = value.trim()
  return /^(https?:|data:|blob:|mailto:)/i.test(trimmed) || /^[\w.+-]+:\/\//.test(trimmed)
}

function lineOk(sf: SourceFile, node: Node) {
  const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf))
  const text = sf.text.split('\n')[line] ?? ''
  return /\/\/\s*i18n-ok:\s*\S/.test(text)
}

function isTranslationCall(expr: Node) {
  if (!ts.isCallExpression(expr)) return false
  const callee = expr.expression
  if (ts.isIdentifier(callee)) {
    return callee.text === 't' || /^t[A-Z]/.test(callee.text) || callee.text === 'translate'
  }
  return ts.isPropertyAccessExpression(callee) && callee.name.text === 't'
}

function unwrap(expr: Expression): Expression {
  let current = expr
  while (
    ts.isParenthesizedExpression(current)
    || ts.isAsExpression(current)
    || ts.isSatisfiesExpression(current)
    || ts.isTypeAssertionExpression(current)
    || ts.isNonNullExpression(current)
  ) {
    current = current.expression
  }
  return current
}

function countValue(expr: Expression | undefined, sf: SourceFile, hits: string[]) {
  if (!expr) return
  const current = unwrap(expr)
  if (ts.isConditionalExpression(current)) {
    countValue(current.whenTrue, sf, hits)
    countValue(current.whenFalse, sf, hits)
    return
  }
  if (ts.isBinaryExpression(current) && isBranchOperator(current.operatorToken.kind)) {
    countValue(current.left, sf, hits)
    countValue(current.right, sf, hits)
    return
  }
  if (isTranslationCall(current)) return
  pushLiteral(current, sf, hits)
}

function isBranchOperator(kind: import('typescript').SyntaxKind) {
  return kind === ts.SyntaxKind.BarBarToken
    || kind === ts.SyntaxKind.QuestionQuestionToken
    || kind === ts.SyntaxKind.AmpersandAmpersandToken
}

function pushLiteral(expr: Expression, sf: SourceFile, hits: string[]) {
  if (ts.isStringLiteral(expr) || ts.isNoSubstitutionTemplateLiteral(expr)) {
    if (hasLetter(expr.text) && !isUrl(expr.text) && !lineOk(sf, expr)) hits.push(expr.text)
    return
  }
  if (!ts.isTemplateExpression(expr)) return
  const staticText = expr.head.text + expr.templateSpans.map(span => span.literal.text).join('')
  if (hasLetter(staticText) && !isUrl(staticText) && !lineOk(sf, expr)) hits.push(staticText)
}

function catalogKey(name: import('typescript').PropertyName) {
  if (ts.isIdentifier(name) || ts.isStringLiteral(name) || ts.isNoSubstitutionTemplateLiteral(name)) return name.text
  if (!ts.isComputedPropertyName(name)) return null
  const expr = unwrap(name.expression)
  if (ts.isStringLiteral(expr) || ts.isNoSubstitutionTemplateLiteral(expr)) return expr.text
  return null
}

function recordJsx(node: Node, sf: SourceFile, hits: string[]) {
  if (ts.isJsxText(node)) {
    if (hasLetter(node.getText(sf)) && !lineOk(sf, node)) hits.push(node.getText(sf).trim())
    return
  }
  if (ts.isJsxAttribute(node) && JSX_ATTRS.has(node.name.getText(sf)) && node.initializer) {
    if (ts.isStringLiteral(node.initializer)) countValue(node.initializer, sf, hits)
    else if (ts.isJsxExpression(node.initializer)) countValue(node.initializer.expression, sf, hits)
    return
  }
  if (ts.isJsxExpression(node) && node.expression && !ts.isJsxAttribute(node.parent)) {
    countValue(node.expression, sf, hits)
  }
}

function recordCatalog(node: Node, sf: SourceFile, hits: string[]) {
  if (!ts.isPropertyAssignment(node)) return
  const key = catalogKey(node.name)
  if (key && CATALOG_KEYS.has(key)) countValue(node.initializer, sf, hits)
}

/** Letter-bearing hardcoded strings in one source file. */
export function literalStringHits(path: string, text: string) {
  const kind = path.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS
  const sf = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, kind)
  const hits: string[] = []
  function visit(node: Node) {
    recordJsx(node, sf, hits)
    recordCatalog(node, sf, hits)
    ts.forEachChild(node, visit)
  }
  visit(sf)
  return hits
}

/** File → hit count for every scanned source file that has at least one hit. */
export function countLiteralStrings() {
  const counts: Record<string, number> = {}
  for (const rel of literalSourceRelPaths()) {
    const hits = literalStringHits(join(uiRoot, rel), readFileSync(join(uiRoot, rel), 'utf8'))
    if (hits.length) counts[rel] = hits.length
  }
  return Object.fromEntries(Object.entries(counts).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0))
}
