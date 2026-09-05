import assert from 'node:assert/strict'
import test from 'node:test'

import {
  extractTypeScriptGraphFromSources,
} from '../scripts/graphs/typescript_graph.mjs'

function sources(overrides = {}) {
  const base = {
    'ui/src/api/director.ts': `
      export async function adoptAudio() {
        const ignored = 'api.uploadAudio()'
        // api.uploadAudio()
        return fetch(\`${'${BASE}'}/api/v1/audio/adopt\`)
      }
      export async function uploadAudio() {
        return fetch(\`${'${BASE}'}/api/v1/upload-audio\`)
      }
      export async function trimAudio() {
        return fetch(\`${'${BASE}'}/api/v1/audio/trim\`)
      }
      export async function startAudioAnalysisJob() {
        return fetch(\`${'${BASE}'}/api/v1/audio/analyze/jobs\`)
      }
    `,
    'ui/src/api/outputs.ts': `
      export function getServerMediaReference(source, filename) { return source ? { audio_path: filename } : null }
      export function getPlayableFileUrl(source, filename) { return getFileUrl(filename) }
      export function getFileUrl(filename) { return \`${'${BASE}'}/api/v1/file/\${filename}\` }
    `,
    'ui/src/stores/useStore.ts': `
      import * as api from '../api/client'
      export const useStore = create(() => ({
        directorAdoptAndAnalyze: async (reference) => {
          const braceText = '{ directorUploadAndAnalyze() }'
          const unrelated = { uploadAudio: () => {} }
          await api.adoptAudio(reference)
          await api.uploadAudio(reference)
          await api.uploadAudio(reference)
          unrelated.uploadAudio(reference)
          set({ directorAudioName: reference.name, directorAnalysis: null })
        },
        directorUploadAndAnalyze: async (file) => get().directorLoadAudioSource(file),
        directorLoadAudioSource: async (source) => get().directorAnalyzeAndPlan(source),
        directorAnalyzeAndPlan: async () => set({ directorAnalysis: {} }),
      }))
    `,
    'ui/src/features/stories/StoryLabPanel.tsx': `
      export function StoryLabPanel() { loadStoryMusicVideoProduction({}) }
    `,
    'ui/src/components/Sidebar/DirectorPanel.tsx': `
      export function DirectorPanel() {
        const action = useStore(s => s.directorUploadAndAnalyze)
        action()
        const audioName = useStore(s => s.directorAudioName)
        return audioName
      }
    `,
    'ui/src/components/Sidebar/DirectorChat.tsx': `
      export function DirectorChat() {
        const action = useStore(s => s.directorAdoptAndAnalyze)
        return action
      }
    `,
    'ui/src/features/stories/storyProductionController.ts': `
      export async function loadStoryMusicVideoProduction() {
        await useStore.getState().directorAdoptAndAnalyze({})
      }
    `,
  }
  return { ...base, ...overrides }
}

test('uses compiler AST and records call-site multiplicity with evidence', () => {
  const graph = extractTypeScriptGraphFromSources(sources())
  const edge = graph.edges.find(item => (
    item.source === 'store.directorAdoptAndAnalyze'
    && item.target === 'api.uploadAudio'
    && item.kind === 'call'
  ))

  assert.equal(edge?.weight, 2)
  assert.equal(edge?.evidence.length, 2)
  assert.ok(edge?.evidence.every(item => item.file.startsWith('ui/')))
  assert.ok(graph.nodes.every(item => item.evidence.every(evidence => !evidence.file.startsWith('/'))))
})

test('ignores fake calls in comments and strings, including brace strings', () => {
  const graph = extractTypeScriptGraphFromSources(sources())
  const edge = graph.edges.find(item => (
    item.source === 'api.adoptAudio'
    && item.target === 'api.uploadAudio'
  ))
  const write = graph.edges.find(item => (
    item.source === 'store.directorAdoptAndAnalyze'
    && item.target === 'store.slice'
    && item.kind === 'write'
  ))

  assert.equal(edge, undefined)
  assert.equal(write?.weight, 0)
  assert.equal(write?.evidence.length, 2)
})

test('finds arrow actions and selector references without regex brace matching', () => {
  const graph = extractTypeScriptGraphFromSources(sources())
  assert.ok(graph.edges.some(item => (
    item.source === 'ui.director_panel'
    && item.target === 'store.directorUploadAndAnalyze'
    && item.kind === 'reference'
    && item.weight === 0
  )))
  assert.ok(graph.edges.some(item => (
    item.source === 'ui.story_lab_panel'
    && item.target === 'ctrl.story_production_controller'
    && item.kind === 'call'
  )))
  assert.ok(graph.edges.some(item => (
    item.source === 'api.getPlayableFileUrl'
    && item.target === 'api.getFileUrl'
    && item.kind === 'call'
  )))
  assert.ok(graph.edges.some(item => (
    item.source === 'api.getFileUrl'
    && item.target === 'route.serve_file'
    && item.kind === 'url'
    && item.label === 'produces URL for'
  )))
})

test('fails closed when a required function is missing', () => {
  const missing = sources({
    'ui/api/does-not-exist.ts': '',
  })
  delete missing['ui/src/api/director.ts']
  assert.throws(
    () => extractTypeScriptGraphFromSources(missing),
    /Missing required TypeScript function|source/,
  )
})

test('fails closed on TypeScript syntax diagnostics and missing exported controller', () => {
  const malformed = sources({
    'ui/src/api/outputs.ts': `${sources()['ui/src/api/outputs.ts']}\nconst =`,
  })
  assert.throws(
    () => extractTypeScriptGraphFromSources(malformed),
    /syntax diagnostics/,
  )

  const unexported = sources({
    'ui/src/features/stories/storyProductionController.ts': `
      async function loadStoryMusicVideoProduction() { return null }
    `,
  })
  assert.throws(
    () => extractTypeScriptGraphFromSources(unexported),
    /Missing required exported TypeScript function/,
  )
})

test('fails closed on ambiguous required function declarations', () => {
  const duplicate = sources({
    'ui/src/api/director.ts': `${sources()['ui/src/api/director.ts']}
      export async function uploadAudio() { return null }
    `,
  })
  assert.throws(
    () => extractTypeScriptGraphFromSources(duplicate),
    /Ambiguous required TypeScript function uploadAudio/,
  )
})

test('produces deterministic fragments and explicit limitations', () => {
  const first = extractTypeScriptGraphFromSources(sources())
  const second = extractTypeScriptGraphFromSources(sources())
  assert.equal(JSON.stringify(first), JSON.stringify(second))
  assert.ok(first.limitations.some(item => item.includes('type or module resolution')))
})
