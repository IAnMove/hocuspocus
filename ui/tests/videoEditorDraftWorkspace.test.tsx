import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'

const clip = {
  id: 'clip-1', name: 'Opening', source: 'opening.mp4', previewUrl: 'opening.mp4', thumbnailUrl: '',
  duration: 12, width: 1920, height: 1080, fps: 30, has_audio: true, pixel_format: 'yuv420p', has_alpha: false,
  trimStart: 1, trimEnd: 10, volume: 1, muted: false, fit: 'fit', transition: 'none', transitionDuration: 0.5,
  transitionText: '', transitionTextSize: 100,
}

test('Video Editor drafts are isolated per workspace and migrate the legacy key once', () => {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, { window: dom.window, document: dom.window.document })
  return import('../src/features/video-editor/editorDraft.ts').then(({
    loadEditorDraft, persistEditorDraft, videoEditorDraftStorageKey,
  }) => {
    dom.window.localStorage.clear()
    const resolution = { label: 'Landscape 480p', width: 864, height: 480 }
    persistEditorDraft([{ ...clip, name: 'Workspace A' }], 'project-a', resolution, 30, 'client-a')
    persistEditorDraft([{ ...clip, id: 'clip-b', name: 'Workspace B' }], 'project-b', resolution, 24, 'client-b')

    const draftA = loadEditorDraft('client-a')
    const draftB = loadEditorDraft('client-b')
    assert.equal(draftA.projectName, 'project-a')
    assert.equal(draftA.clips[0].name, 'Workspace A')
    assert.equal(draftA.fps, 30)
    assert.equal(draftB.projectName, 'project-b')
    assert.equal(draftB.clips[0].name, 'Workspace B')
    assert.equal(draftB.fps, 24)
    assert.equal(dom.window.localStorage.getItem(videoEditorDraftStorageKey('client-a'))?.includes('project-a'), true)
    assert.equal(dom.window.localStorage.getItem(videoEditorDraftStorageKey('client-b'))?.includes('project-b'), true)

    dom.window.localStorage.setItem('maestro-video-editor-draft-v1', JSON.stringify({
      projectName: 'legacy',
      resolution,
      fps: 25,
      clips: [{ ...clip, name: 'Legacy clip' }],
    }))
    const migrated = loadEditorDraft('default')
    assert.equal(migrated.projectName, 'legacy')
    assert.equal(migrated.clips[0].name, 'Legacy clip')
    assert.equal(dom.window.localStorage.getItem('maestro-video-editor-draft-v1'), null)
    assert.ok(dom.window.localStorage.getItem(videoEditorDraftStorageKey('default')))
    const other = loadEditorDraft('client-a')
    assert.equal(other.projectName, 'project-a')
  })
})
