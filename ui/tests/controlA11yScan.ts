import { readdirSync, readFileSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * Source scanners for icon-only controls and disabled controls.
 *
 * An icon-only control is a JSX `<button>` or `<a>` whose children are only
 * lucide-react icons (or a span/div/fragment wrapping those icons) and which
 * has neither `aria-label` nor `title` on that element.
 *
 * A silent disabled control is a JSX element with `disabled` (not the literal
 * `false`) and neither `title` nor `aria-describedby` on that element.
 *
 * Every `.tsx` file under `ui/src` is in scope, including Video 3D and the
 * workbench.
 */
const uiRoot = fileURLToPath(new URL('..', import.meta.url))
const require = createRequire(join(uiRoot, 'package.json'))
const ts = require('typescript') as typeof import('typescript')

const PASSTHROUGH = new Set(['span', 'div', 'i', 'em', 'strong'])

export interface ScanHit {
  line: number
  column: number
  text: string
}

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

/** Relative `.tsx` paths the icon and disabled scanners read. */
export function scannedUiSources() {
  return sourceFiles(join(uiRoot, 'src')).map(path => relative(uiRoot, path).split('\\').join('/')).sort()
}

function lucideNames(sf: import('typescript').SourceFile) {
  const names = new Set<string>()
  const namespaces = new Set<string>()
  for (const stmt of sf.statements) {
    if (!ts.isImportDeclaration(stmt) || !ts.isStringLiteral(stmt.moduleSpecifier)) continue
    if (stmt.moduleSpecifier.text !== 'lucide-react' || !stmt.importClause) continue
    const named = stmt.importClause.namedBindings
    if (named && ts.isNamespaceImport(named)) namespaces.add(named.name.text)
    if (!named || !ts.isNamedImports(named)) continue
    for (const element of named.elements) names.add(element.name.text)
  }
  return { names, namespaces }
}

function attrName(attr: import('typescript').JsxAttribute) {
  return ts.isIdentifier(attr.name) ? attr.name.text : attr.name.getText()
}

function hasAnyAttr(opening: import('typescript').JsxOpeningElement | import('typescript').JsxSelfClosingElement, names: Set<string>) {
  return opening.attributes.properties.some(attr => ts.isJsxAttribute(attr) && names.has(attrName(attr)))
}

function disabledIsLiteralFalse(attr: import('typescript').JsxAttribute) {
  const init = attr.initializer
  if (!init || !ts.isJsxExpression(init) || !init.expression) return false
  return init.expression.kind === ts.SyntaxKind.FalseKeyword
}

function elementTag(node: import('typescript').JsxElement | import('typescript').JsxSelfClosingElement | import('typescript').JsxFragment) {
  if (ts.isJsxFragment(node)) return null
  const opening = ts.isJsxElement(node) ? node.openingElement : node
  return opening.tagName
}

function intrinsic(tag: import('typescript').JsxTagNameExpression) {
  return ts.isIdentifier(tag) ? tag.text : null
}

type IconKind = 'icon' | 'empty' | 'other'

function unwrap(expr: import('typescript').Expression): import('typescript').Expression {
  let current = expr
  while (
    ts.isParenthesizedExpression(current)
    || ts.isAsExpression(current)
    || ts.isSatisfiesExpression(current)
    || ts.isTypeAssertionExpression(current)
    || ts.isNonNullExpression(current)
  ) current = current.expression
  return current
}

function tagIsIcon(tag: import('typescript').JsxTagNameExpression, icons: Set<string>, namespaces: Set<string>) {
  if (ts.isIdentifier(tag)) return tag.text === 'svg' || icons.has(tag.text)
  if (ts.isPropertyAccessExpression(tag) && ts.isIdentifier(tag.expression)) {
    return namespaces.has(tag.expression.text)
  }
  return false
}

function classifyElement(
  node: import('typescript').JsxElement | import('typescript').JsxSelfClosingElement | import('typescript').JsxFragment,
  icons: Set<string>,
  namespaces: Set<string>,
): IconKind {
  if (ts.isJsxFragment(node)) return foldChildren(node.children, icons, namespaces)
  const tag = elementTag(node)
  if (!tag) return 'other'
  const children = ts.isJsxElement(node) ? node.children : []
  if (tagIsIcon(tag, icons, namespaces)) {
    const nested = foldChildren(children, icons, namespaces)
    return nested === 'other' ? 'other' : 'icon'
  }
  const name = intrinsic(tag)
  if (name && PASSTHROUGH.has(name)) return foldChildren(children, icons, namespaces)
  return 'other'
}

function foldChildren(
  children: readonly import('typescript').Node[],
  icons: Set<string>,
  namespaces: Set<string>,
): IconKind {
  let sawIcon = false
  for (const child of children) {
    const kind = classifyNode(child, icons, namespaces)
    if (kind === 'other') return 'other'
    if (kind === 'icon') sawIcon = true
  }
  return sawIcon ? 'icon' : 'empty'
}

function classifyExpression(expr: import('typescript').Expression, icons: Set<string>, namespaces: Set<string>): IconKind {
  const current = unwrap(expr)
  if (current.kind === ts.SyntaxKind.TrueKeyword || current.kind === ts.SyntaxKind.FalseKeyword) return 'empty'
  if (ts.isIdentifier(current) && (current.text === 'undefined' || current.text === 'null')) return 'empty'
  if (ts.isStringLiteral(current) || ts.isNoSubstitutionTemplateLiteral(current)) {
    return current.text.trim() ? 'other' : 'empty'
  }
  if (ts.isJsxElement(current) || ts.isJsxSelfClosingElement(current) || ts.isJsxFragment(current)) {
    return classifyElement(current, icons, namespaces)
  }
  if (ts.isConditionalExpression(current)) {
    return foldKinds([
      classifyExpression(current.whenTrue, icons, namespaces),
      classifyExpression(current.whenFalse, icons, namespaces),
    ])
  }
  if (ts.isBinaryExpression(current)) {
    const op = current.operatorToken.kind
    if (op === ts.SyntaxKind.AmpersandAmpersandToken || op === ts.SyntaxKind.BarBarToken) {
      return foldKinds([
        classifyExpression(current.left, icons, namespaces),
        classifyExpression(current.right, icons, namespaces),
      ])
    }
  }
  return 'other'
}

function foldKinds(kinds: IconKind[]): IconKind {
  if (kinds.some(kind => kind === 'other')) return 'other'
  return kinds.some(kind => kind === 'icon') ? 'icon' : 'empty'
}

function classifyNode(node: import('typescript').Node, icons: Set<string>, namespaces: Set<string>): IconKind {
  if (ts.isJsxText(node)) return node.getText().trim() ? 'other' : 'empty'
  if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node) || ts.isJsxFragment(node)) {
    return classifyElement(node, icons, namespaces)
  }
  if (ts.isJsxExpression(node)) {
    if (!node.expression) return 'empty'
    return classifyExpression(node.expression, icons, namespaces)
  }
  return 'empty'
}

const NAMED = new Set(['aria-label', 'title'])
const LABEL_ONLY = new Set(['aria-label'])
const DESCRIBED = new Set(['title', 'aria-describedby'])

function snippet(sf: import('typescript').SourceFile, node: import('typescript').Node) {
  return node.getText(sf).replace(/\s+/g, ' ').slice(0, 180)
}

function at(sf: import('typescript').SourceFile, node: import('typescript').Node): ScanHit {
  const { line, character } = sf.getLineAndCharacterOfPosition(node.getStart(sf))
  return { line: line + 1, column: character + 1, text: snippet(sf, node) }
}

function iconControlHits(path: string, text: string, missing: Set<string>) {
  const sf = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const { names, namespaces } = lucideNames(sf)
  const hits: ScanHit[] = []
  function visit(node: import('typescript').Node) {
    if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)) {
      const opening = ts.isJsxElement(node) ? node.openingElement : node
      const tag = intrinsic(opening.tagName)
      if ((tag === 'button' || tag === 'a') && !hasAnyAttr(opening, missing)) {
        const children = ts.isJsxElement(node) ? node.children : []
        if (foldChildren(children, names, namespaces) === 'icon') hits.push(at(sf, opening))
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(sf)
  return hits
}

/** Icon-only `<button>` / `<a>` with neither `aria-label` nor `title`. */
export function iconHits(path: string, text: string) {
  return iconControlHits(path, text, NAMED)
}

/** Icon-only `<button>` / `<a>` with no `aria-label`, even when `title` is set. */
export function iconMissingLabelHits(path: string, text: string) {
  return iconControlHits(path, text, LABEL_ONLY)
}

export function disabledHits(path: string, text: string) {
  const sf = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const hits: ScanHit[] = []
  function visit(node: import('typescript').Node) {
    if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)) {
      const opening = ts.isJsxElement(node) ? node.openingElement : node
      const disabled = opening.attributes.properties.find(attr => ts.isJsxAttribute(attr) && attrName(attr) === 'disabled')
      if (disabled && ts.isJsxAttribute(disabled) && !disabledIsLiteralFalse(disabled) && !hasAnyAttr(opening, DESCRIBED)) {
        hits.push(at(sf, opening))
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(sf)
  return hits
}

const FIELD_TAGS = new Set(['input', 'select', 'textarea'])
const SKIP_INPUT_TYPES = new Set(['hidden', 'button', 'submit', 'reset', 'image'])

function jsxAttr(opening: import('typescript').JsxOpeningElement | import('typescript').JsxSelfClosingElement, name: string) {
  const found = opening.attributes.properties.find(attr => ts.isJsxAttribute(attr) && attrName(attr) === name)
  return found && ts.isJsxAttribute(found) ? found : undefined
}

/** Stable identity for an `id` / `htmlFor` value so a literal or the same expression links. */
function attrIdentity(attr: import('typescript').JsxAttribute | undefined) {
  const init = attr?.initializer
  if (!init) return null
  if (ts.isStringLiteral(init)) return `lit:${init.text}`
  if (!ts.isJsxExpression(init) || !init.expression) return null
  const expr = unwrap(init.expression)
  if (ts.isStringLiteral(expr) || ts.isNoSubstitutionTemplateLiteral(expr)) return `lit:${expr.text}`
  return `expr:${expr.getText()}`
}

function inputTypeLiteral(opening: import('typescript').JsxOpeningElement | import('typescript').JsxSelfClosingElement) {
  const init = jsxAttr(opening, 'type')?.initializer
  if (!init) return null
  if (ts.isStringLiteral(init)) return init.text
  if (!ts.isJsxExpression(init) || !init.expression) return null
  const expr = unwrap(init.expression)
  return ts.isStringLiteral(expr) || ts.isNoSubstitutionTemplateLiteral(expr) ? expr.text : null
}

function attrIsBlank(attr: import('typescript').JsxAttribute) {
  const init = attr.initializer
  if (!init) return false
  if (ts.isStringLiteral(init)) return !init.text.trim()
  if (!ts.isJsxExpression(init) || !init.expression) return false
  const expr = unwrap(init.expression)
  return (ts.isStringLiteral(expr) || ts.isNoSubstitutionTemplateLiteral(expr)) && !expr.text.trim()
}

function htmlForIds(sf: import('typescript').SourceFile) {
  const ids = new Set<string>()
  function visit(node: import('typescript').Node) {
    if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)) {
      const opening = ts.isJsxElement(node) ? node.openingElement : node
      if (intrinsic(opening.tagName) === 'label') {
        const id = attrIdentity(jsxAttr(opening, 'htmlFor'))
        if (id) ids.add(id)
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(sf)
  return ids
}

function insideLabel(node: import('typescript').Node) {
  let current = node.parent
  while (current) {
    if (ts.isJsxElement(current) && intrinsic(current.openingElement.tagName) === 'label') return true
    current = current.parent
  }
  return false
}

function fieldHasName(opening: import('typescript').JsxOpeningElement | import('typescript').JsxSelfClosingElement) {
  for (const name of ['aria-label', 'aria-labelledby']) {
    const attr = jsxAttr(opening, name)
    if (attr && !attrIsBlank(attr)) return true
  }
  return false
}

function skippedField(tag: string, opening: import('typescript').JsxOpeningElement | import('typescript').JsxSelfClosingElement) {
  if (tag !== 'input') return false
  const type = inputTypeLiteral(opening)
  return type != null && SKIP_INPUT_TYPES.has(type.toLowerCase())
}

/**
 * `<input>`, `<select>` and `<textarea>` with no `aria-label` / `aria-labelledby`,
 * no ancestor `<label>`, and no `id` that an `htmlFor` in the same file uses.
 * `type="hidden|button|submit|reset|image"` is not a form field.
 */
export function fieldHits(path: string, text: string) {
  const sf = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const linked = htmlForIds(sf)
  const hits: ScanHit[] = []
  function visit(node: import('typescript').Node) {
    if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)) {
      const opening = ts.isJsxElement(node) ? node.openingElement : node
      const tag = intrinsic(opening.tagName)
      if (tag && FIELD_TAGS.has(tag) && !skippedField(tag, opening) && !fieldHasName(opening) && !insideLabel(node)) {
        const id = attrIdentity(jsxAttr(opening, 'id'))
        if (!id || !linked.has(id)) hits.push(at(sf, opening))
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(sf)
  return hits
}

export function scanFieldCounts() {
  const counts: Record<string, number> = {}
  for (const rel of scannedUiSources()) {
    const hits = fieldHits(rel, readFileSync(join(uiRoot, rel), 'utf8'))
    if (hits.length) counts[rel] = hits.length
  }
  return Object.fromEntries(Object.entries(counts).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0))
}

export function scanCounts(kind: 'icon' | 'disabled') {
  const counts: Record<string, number> = {}
  for (const rel of scannedUiSources()) {
    const hits = (kind === 'icon' ? iconHits : disabledHits)(rel, readFileSync(join(uiRoot, rel), 'utf8'))
    if (hits.length) counts[rel] = hits.length
  }
  return Object.fromEntries(Object.entries(counts).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0))
}

export function compareBudget(budget: Record<string, number>, actual: Record<string, number>, fileName: string) {
  const problems: string[] = []
  for (const path of [...new Set([...Object.keys(budget), ...Object.keys(actual)])].sort()) {
    const allowed = budget[path] ?? 0
    const seen = actual[path] ?? 0
    if (seen > allowed && !(path in budget)) problems.push(`${path} is not in the budget and has ${seen}`)
    else if (seen > allowed) problems.push(`${path} rose from ${allowed} to ${seen}`)
    else if (seen < allowed) problems.push(`${path} fell from ${allowed} to ${seen}: lower ui/tests/${fileName}`)
  }
  return problems
}
