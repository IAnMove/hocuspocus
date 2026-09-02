import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const NAMESPACES = ['common', 'navigation', 'settings', 'wizard', 'activity', 'extraInfo', 'storyLab']
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
  'src/features/stories/storyLabChrome.tsx',
  'src/features/stories/StoryLabNavigation.tsx',
  'src/features/stories/storyLabTabs.ts',
  'src/features/stories/StoryLabLibraryChrome.tsx',
  'src/features/stories/StoryAssemblyTab.tsx',
  'src/features/stories/StoryOverviewTab.tsx',
  'src/features/stories/StoryAssetsTab.tsx',
  'src/features/stories/StoryAssetsImporter.tsx',
  'src/features/stories/StoryAssetsProposalCard.tsx',
  'src/features/stories/StoryAssetsStyleConverter.tsx',
  'src/features/stories/StoryAssetsLibrary.tsx',
  'src/features/stories/StoryProviderPanel.tsx',
  'src/features/stories/StoryProviderWritingFields.tsx',
  'src/features/stories/StoryProviderImageFields.tsx',
  'src/features/stories/ReferenceGallery.tsx',
  'src/features/stories/LocationEditor.tsx',
  'src/features/stories/CharacterEditor.tsx',
  'src/features/stories/BeatEditor.tsx',
  'src/features/stories/StoryWorldTab.tsx',
  'src/features/stories/StoryCharactersTab.tsx',
  'src/features/stories/StoryStructureTab.tsx',
  'src/features/stories/StoryRelationshipsTab.tsx',
  'src/features/stories/StoryMusicTab.tsx',
  'src/features/stories/StoryMusicHeader.tsx',
  'src/features/stories/StoryMusicSettingsBar.tsx',
  'src/features/stories/MusicCueCard.tsx',
  'src/features/stories/ManualSongPanel.tsx',
  'src/features/stories/StoryTrailerTab.tsx',
  'src/features/stories/StoryTrailerNarrativeForm.tsx',
  'src/features/stories/StoryTrailerTimeline.tsx',
  'src/features/stories/StoryTrailerClipProduction.tsx',
  'src/features/stories/StoryProductionsTab.tsx',
  'src/features/stories/StoryComicProductionCard.tsx',
  'src/features/stories/StoryFilmProductionCard.tsx',
  'src/features/stories/StoryProductionIssuesBanner.tsx',
  'src/features/stories/StoryProductionsMusicPanel.tsx',
  'src/features/stories/StoryMusicProductionSong.tsx',
  'src/features/stories/StoryMusicProductionGuide.tsx',
  'src/features/stories/StoryMusicProductionModels.tsx',
  'src/features/stories/StoryMusicProductionLaunch.tsx',
  'src/features/stories/StoryMusicProductionLegacyDrawer.tsx',
  'src/features/stories/CompactVideoWorkspace.tsx',
  'src/features/stories/CompactPrepStatus.tsx',
  'src/features/stories/CompactWorldArticle.tsx',
  'src/features/stories/CompactCastArticle.tsx',
  'src/features/stories/CompactSequenceArticle.tsx',
  'src/features/stories/CompactSubjectEditor.tsx',
  'src/features/stories/CompactBeatEditor.tsx',
  'src/features/stories/StoryVideoFormatControls.tsx',
]

const FORBIDDEN = [
  'Ask to the Wizard',
  'Output folders',
  'Pregunta al mago',
  'Carpetas de salida',
  'Extra info',
  'Clip information',
  'Wait for generation to finish',
  'World bible',
  'Dramatic structure',
  'Generate text',
  'Optional regeneration instruction…',
  'Music bible',
  'Cinematic trailer creator',
  'Generate / refresh Lyria prompt',
  'Import custom MP3',
  'Montaje de producciones',
  'Smart assets',
  'Guided · approve stages',
  'Preparar historia completa · solo texto',
  'Desliza para más secciones',
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
