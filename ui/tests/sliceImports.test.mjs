import assert from 'node:assert/strict'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

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

function isTypeOnlyClause(clause) {
  const trimmed = clause.trim()
  if (/^type\b/.test(trimmed)) return true
  const braceAt = trimmed.indexOf('{')
  if (braceAt === -1) return false
  if (trimmed.slice(0, braceAt).trim()) return false
  const parts = trimmed.slice(braceAt + 1, trimmed.lastIndexOf('}')).split(',').map(part => part.trim()).filter(Boolean)
  return parts.length > 0 && parts.every(part => /^type\b/.test(part))
}

function runtimeUseStoreImports(file, text) {
  const found = []
  const fromImport = /(?:^|\n)\s*(import|export)\s+([\s\S]*?)\sfrom\s+['"]([^'"]+)['"]/g
  for (const match of text.matchAll(fromImport)) {
    if (!pointsAtUseStore(file, match[3])) continue
    if (isTypeOnlyClause(match[2])) continue
    found.push(match[3])
  }
  const dynamicImport = /import\s*\(\s*['"]([^'"]+)['"]\s*\)/g
  for (const match of text.matchAll(dynamicImport)) {
    if (pointsAtUseStore(file, match[1])) found.push(match[1])
  }
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
