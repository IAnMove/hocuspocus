import assert from 'node:assert/strict'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const uiRoot = fileURLToPath(new URL('..', import.meta.url))
const storeModule = 'useStore'
const useStorePath = resolve(uiRoot, 'src/stores', `${storeModule}.ts`)

function sourceFiles(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) {
      if (name === 'node_modules' || name === 'dist' || name === 'tests' || name === '__tests__') continue
      sourceFiles(path, out)
      continue
    }
    if (/\.(ts|tsx)$/.test(name) && !/\.(test|spec)\.(ts|tsx)$/.test(name)) out.push(path)
  }
  return out
}

function exportsCreateSlice(text) {
  return /export\s+(?:async\s+)?function\s+create\w*Slice\b/.test(text)
    || /export\s+(?:const|let|var)\s+create\w*Slice\b/.test(text)
    || /export\s*\{[^}]*\bcreate\w*Slice\b[^}]*\}/.test(text)
    || /export\s*\{[^}]*\bcreate\w*Slice\b[^}]*\}\s*from/.test(text)
}

function pointsAtUseStore(fromFile, specifier) {
  const storeFile = `${storeModule}.ts`
  if (specifier === `stores/${storeModule}` || specifier.endsWith(`/stores/${storeModule}`) || specifier.endsWith(`/stores/${storeFile}`)) {
    return true
  }
  if (!specifier.startsWith('.')) return false
  let target = resolve(dirname(fromFile), specifier)
  if (!/\.(ts|tsx)$/.test(target)) target += '.ts'
  return target === useStorePath
}

function isTypeOnlyImport(node) {
  const clause = node.importClause
  if (!clause) return false
  if (clause.isTypeOnly) return true
  if (clause.name) return false
  const bindings = clause.namedBindings
  return Boolean(bindings && ts.isNamedImports(bindings)
    && bindings.elements.length > 0 && bindings.elements.every(element => element.isTypeOnly))
}

function isTypeOnlyExport(node) {
  if (node.isTypeOnly) return true
  const clause = node.exportClause
  return Boolean(clause && ts.isNamedExports(clause)
    && clause.elements.length > 0 && clause.elements.every(element => element.isTypeOnly))
}

/** Parsed with the TypeScript compiler, so a statement can never swallow the
 *  next one the way a regular expression over the source text can. */
function runtimeUseStoreImports(file, text) {
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true,
    file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS)
  const found = []
  const visit = node => {
    if (ts.isImportDeclaration(node) && !isTypeOnlyImport(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      if (pointsAtUseStore(file, node.moduleSpecifier.text)) found.push(node.moduleSpecifier.text)
    } else if (ts.isExportDeclaration(node) && node.moduleSpecifier && !isTypeOnlyExport(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      if (pointsAtUseStore(file, node.moduleSpecifier.text)) found.push(node.moduleSpecifier.text)
    } else if (ts.isImportEqualsDeclaration(node) && !node.isTypeOnly && ts.isExternalModuleReference(node.moduleReference)
      && ts.isStringLiteral(node.moduleReference.expression)) {
      if (pointsAtUseStore(file, node.moduleReference.expression.text)) found.push(node.moduleReference.expression.text)
    } else if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword
      && node.arguments.length > 0 && ts.isStringLiteralLike(node.arguments[0])) {
      if (pointsAtUseStore(file, node.arguments[0].text)) found.push(node.arguments[0].text)
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  return found
}

test('createSlice modules do not load the root store module at runtime', () => {
  const offenders = []
  let slices = 0
  for (const file of sourceFiles(join(uiRoot, 'src'))) {
    const text = readFileSync(file, 'utf8')
    if (!exportsCreateSlice(text)) continue
    slices += 1
    const bad = runtimeUseStoreImports(file, text)
    if (bad.length) offenders.push(`${relative(uiRoot, file)} imports ${bad.join(', ')}`)
  }
  assert.ok(slices >= 10, `expected the existing slice creators, found ${slices}`)
  assert.deepEqual(offenders, [])
})
