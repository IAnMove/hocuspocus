import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const NAMESPACES = ['common', 'navigation', 'settings', 'wizard', 'activity']
const LANGUAGES = ['en', 'es']

function load(language, namespace) {
  return JSON.parse(readFileSync(join(ROOT, 'src/i18n/locales', language, `${namespace}.json`), 'utf8'))
}

function keys(value, prefix = '') {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return prefix ? [prefix] : []
  return Object.entries(value).flatMap(([key, child]) => keys(child, prefix ? `${prefix}.${key}` : key))
}

export function catalogReport() {
  const catalogs = Object.fromEntries(LANGUAGES.map(language => [
    language,
    Object.fromEntries(NAMESPACES.map(namespace => [namespace, load(language, namespace)])),
  ]))
  const missing = []
  for (const namespace of NAMESPACES) {
    const enKeys = new Set(keys(catalogs.en[namespace]))
    const esKeys = new Set(keys(catalogs.es[namespace]))
    for (const key of enKeys) if (!esKeys.has(key)) missing.push(`es/${namespace}: ${key}`)
    for (const key of esKeys) if (!enKeys.has(key)) missing.push(`en/${namespace}: ${key}`)
  }
  return { catalogs, missing }
}

const PILOT_FILES = [
  'src/components/MainContent/TabFilter.tsx',
  'src/components/MainContent/MainContent.tsx',
  'src/components/MainContent/MediaFeedItem.tsx',
  'src/components/MainContent/VideoExtraInfoDialog.tsx',
  'src/components/MainContent/VideoInfoBar.tsx',
  'src/components/SettingsDrawer/SettingsDrawer.tsx',
  'src/components/SettingsDrawer/SystemSettingsPanel.tsx',
  'src/components/ActivityFooter.tsx',
  'src/features/agent/AgentAssistantPanel.tsx',
  'src/features/assets/AssetsPanel.tsx',
  'src/features/workspaceCollections/WorkspaceCollectionsPanel.tsx',
  'src/features/workspaces/WorkspacesPanel.tsx',
]

const FORBIDDEN = [
  'Ask to the Wizard',
  'Output folders',
  'Pregunta al mago',
  'Carpetas de salida',
  'Extra info',
]

export function forbiddenLiterals() {
  const hits = []
  for (const file of PILOT_FILES) {
    const source = readFileSync(join(ROOT, file), 'utf8')
    for (const phrase of FORBIDDEN) {
      if (source.includes(`"${phrase}"`) || source.includes(`'${phrase}'`) || source.includes(`>${phrase}<`)) {
        hits.push(`${file}: ${phrase}`)
      }
    }
  }
  return hits
}

if (import.meta.url === `file://${process.argv[1]}` || process.argv[1]?.endsWith('check-i18n-catalogs.mjs')) {
  const { missing } = catalogReport()
  const hits = forbiddenLiterals()
  assert.deepEqual(missing, [], missing.join('\n'))
  assert.deepEqual(hits, [], hits.join('\n'))
  console.log(`i18n catalogs ok (${NAMESPACES.length} namespaces, ${LANGUAGES.join('/')})`)
}
