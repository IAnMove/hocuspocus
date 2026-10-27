import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

/**
 * Hardcoded user-visible strings in `ui/src/**\/*.tsx`.
 *
 * Counts JSX text that contains a letter, the same strings when they are a
 * JSX child expression, and string literals passed to `title`, `placeholder`,
 * `aria-label`, `alt` or `label` (including `||`, `??`, `&&` and ternary
 * branches, not the condition). Skips `t(...)`, `tStudio`-style helpers,
 * `translate`, className, id, URLs, and a line marked `// i18n-ok: reason`.
 *
 * Object-literal catalogues (`label: 'Music Video'`) are not counted; those
 * are translated at the render site. `features/scene3d` and
 * `components/workbench` are excluded until the run that owns them adds them.
 */
const uiRoot = fileURLToPath(new URL('..', import.meta.url))
const require = createRequire(join(uiRoot, 'package.json'))
const ts = require('typescript') as typeof import('typescript')

const ATTRS = new Set(['title', 'placeholder', 'aria-label', 'alt', 'label'])
const EXCLUDE_PREFIXES = ['src/features/scene3d/', 'src/components/workbench/']

function sourceFiles(dir: string, out: string[] = []) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) {
      if (name === 'node_modules' || name === 'dist' || name === 'tests' || name === '__tests__') continue
      sourceFiles(path, out)
      continue
    }
    if (name.endsWith('.tsx')) out.push(path)
  }
  return out
}

function hasLetter(value: string) {
  const visible = value.replace(/&(?:#x[0-9a-fA-F]+|#\d+|[a-zA-Z]+);/g, '')
  return /\p{L}/u.test(visible)
}

function isUrl(value: string) {
  const trimmed = value.trim()
  return /^(https?:|data:|blob:|mailto:)/i.test(trimmed) || /^[\w.+-]+:\/\//.test(trimmed)
}

function lineOk(sf: import('typescript').SourceFile, node: import('typescript').Node) {
  const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf))
  const text = sf.text.split('\n')[line] ?? ''
  return /\/\/\s*i18n-ok:\s*\S/.test(text)
}

function isTranslationCall(expr: import('typescript').Node) {
  if (!ts.isCallExpression(expr)) return false
  const callee = expr.expression
  if (ts.isIdentifier(callee)) {
    return callee.text === 't' || /^t[A-Z]/.test(callee.text) || callee.text === 'translate'
  }
  return ts.isPropertyAccessExpression(callee) && callee.name.text === 't'
}

function unwrap(expr: import('typescript').Expression): import('typescript').Expression {
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

function countValue(expr: import('typescript').Expression | undefined, sf: import('typescript').SourceFile, hits: string[]) {
  if (!expr) return
  const current = unwrap(expr)
  if (ts.isConditionalExpression(current)) {
    countValue(current.whenTrue, sf, hits)
    countValue(current.whenFalse, sf, hits)
    return
  }
  if (ts.isBinaryExpression(current)) {
    const op = current.operatorToken.kind
    if (
      op === ts.SyntaxKind.BarBarToken
      || op === ts.SyntaxKind.QuestionQuestionToken
      || op === ts.SyntaxKind.AmpersandAmpersandToken
    ) {
      countValue(current.left, sf, hits)
      countValue(current.right, sf, hits)
    }
    return
  }
  if (isTranslationCall(current)) return
  if (ts.isStringLiteral(current) || ts.isNoSubstitutionTemplateLiteral(current)) {
    if (hasLetter(current.text) && !isUrl(current.text) && !lineOk(sf, current)) hits.push(current.text)
    return
  }
  if (ts.isTemplateExpression(current)) {
    const staticText = current.head.text + current.templateSpans.map(span => span.literal.text).join('')
    if (hasLetter(staticText) && !isUrl(staticText) && !lineOk(sf, current)) hits.push(staticText)
  }
}

function countFile(path: string) {
  const text = readFileSync(path, 'utf8')
  const sf = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const hits: string[] = []
  function visit(node: import('typescript').Node) {
    if (ts.isJsxText(node)) {
      if (hasLetter(node.getText(sf)) && !lineOk(sf, node)) hits.push(node.getText(sf).trim())
    } else if (ts.isJsxAttribute(node) && ATTRS.has(node.name.getText(sf)) && node.initializer) {
      if (ts.isStringLiteral(node.initializer)) countValue(node.initializer, sf, hits)
      else if (ts.isJsxExpression(node.initializer)) countValue(node.initializer.expression, sf, hits)
    } else if (ts.isJsxExpression(node) && node.expression && !ts.isJsxAttribute(node.parent)) {
      countValue(node.expression, sf, hits)
    }
    ts.forEachChild(node, visit)
  }
  visit(sf)
  return hits
}

function countLiteralStrings() {
  const counts: Record<string, number> = {}
  for (const path of sourceFiles(join(uiRoot, 'src'))) {
    const rel = relative(uiRoot, path).split('\\').join('/')
    if (EXCLUDE_PREFIXES.some(prefix => rel.startsWith(prefix))) continue
    const hits = countFile(path)
    if (hits.length) counts[rel] = hits.length
  }
  return Object.fromEntries(Object.entries(counts).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0))
}

test('hardcoded user-visible strings stay inside the budget', () => {
  const budget = JSON.parse(readFileSync(new URL('./literalStringBudget.json', import.meta.url), 'utf8')) as Record<string, number>
  const actual = countLiteralStrings()
  const problems: string[] = []
  for (const path of [...new Set([...Object.keys(budget), ...Object.keys(actual)])].sort()) {
    const allowed = budget[path] ?? 0
    const seen = actual[path] ?? 0
    if (seen > allowed && !(path in budget)) {
      problems.push(`${path} is not in the budget and has ${seen} hardcoded string(s)`)
    } else if (seen > allowed) {
      problems.push(`${path} rose from ${allowed} to ${seen}`)
    } else if (seen < allowed) {
      problems.push(`${path} fell from ${allowed} to ${seen}: lower ui/tests/literalStringBudget.json`)
    }
  }
  assert.deepEqual(problems, [], problems.join('\n'))
})
