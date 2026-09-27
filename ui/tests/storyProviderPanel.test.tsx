import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  Event: dom.window.Event, MutationObserver: dom.window.MutationObserver, localStorage: dom.window.localStorage,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const { render, screen, cleanup } = await import('@testing-library/react')
const { useStore } = await import('../src/stores/useStore')
const { ensureUiI18n, setUiLanguage } = await import('../src/i18n/index.ts')
const { createStoryProject } = await import('../src/features/stories/model')
const { StoryProviderPanel } = await import('../src/features/stories/StoryProviderPanel')

test('an Ollama writing override is shown as Ollama and reported ready', async () => {
  ensureUiI18n()
  await setUiLanguage('en')
  const initial = useStore.getState()
  const project = createStoryProject()
  project.provider = {
    ...project.provider,
    useGlobalProfile: false,
    writingProvider: 'ollama',
    writingModel: 'gemma4:12b',
    writingBaseUrl: 'http://127.0.0.1:11434',
  }
  useStore.setState({ servicesConfig: null, models: [] })
  try {
    render(
      <StoryProviderPanel
        project={project}
        patch={() => {}}
        onProfileModeChange={() => {}}
        videoFormatControls={<p>shared format controls</p>}
      />,
    )
    const select = screen.getByDisplayValue('Ollama (local)') as HTMLSelectElement
    assert.equal(select.value, 'ollama')
    assert.ok(screen.getByText('Writing provider ready.'))
    assert.equal(screen.queryByText(/Missing provider credentials/), null)
    assert.ok(screen.getByText('shared format controls'))
  } finally {
    cleanup()
    useStore.setState(initial)
  }
})

test('Story Lab format uses the Studio selectors with only 16:9 and 9:16', async () => {
  const { fireEvent } = await import('@testing-library/react')
  const { StoryVideoFormatControls } = await import('../src/features/stories/StoryVideoFormatControls')
  ensureUiI18n()
  await setUiLanguage('en')
  const changes: Array<[string, string]> = []
  try {
    render(
      <StoryVideoFormatControls
        videoModel="minimax_h3_fused_turbo"
        resolution="540p"
        aspectRatio="16:9"
        options={null}
        disabled={false}
        inherited
        adjusted={false}
        onChange={(resolution, aspect) => changes.push([resolution, aspect])}
      />,
    )
    const ratios = screen.getAllByRole('button').map(button => button.textContent || '')
      .filter(text => /\d+:\d+|Auto/.test(text))
    assert.deepEqual(ratios.map(text => text.replace(/[^\d:A-Za-z]/g, '')), ['16:9', '9:16'])
    fireEvent.click(screen.getByRole('button', { name: /9:16/ }))
    fireEvent.click(screen.getByRole('button', { name: '720p' }))
    assert.deepEqual(changes, [['540p', '9:16'], ['720p', '16:9']])
  } finally {
    cleanup()
  }
})

test('the shared character style drops clauses about individual characters', async () => {
  const { directVideoMasterPromptFromVisualStyles, stripCharacterSpecificStyle } = await import('../src/features/stories/model')
  const style = 'Stylized 3D characters with expressive features; Pip has large glossy eyes; Owl is fluffy with scholarly features.'
  const cast = ['Pip', 'Barnaby', 'Sasha', 'Great Wise Owl']
  assert.equal(stripCharacterSpecificStyle(style, cast), 'Stylized 3D characters with expressive features')
  // Words that merely contain a name, or title words, are not treated as names.
  assert.equal(stripCharacterSpecificStyle('Great detail; pipeline-ready fur shading.', cast), 'Great detail; pipeline-ready fur shading.')
  const prompt = directVideoMasterPromptFromVisualStyles('Pixar-like forest', style, cast)
  assert.match(prompt, /CHARACTER VISUAL STYLE \(mandatory for every visible character\): Stylized 3D characters with expressive features\n/)
  assert.doesNotMatch(prompt, /Owl is fluffy|Pip has/)
  assert.match(prompt, /CHARACTER INTEGRITY: every character is exactly one species/)
})
