import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
  return dom
}

installDom()

test('Story Lab navigation exposes every section in a scrollable mobile row', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { BookOpen, ImagePlus, Music } = await import('lucide-react')
  const { StoryLabNavigation } = await import('../src/features/stories/StoryLabNavigation.tsx')
  const tabs = [
    { id: 'overview', label: 'Story', icon: BookOpen },
    { id: 'assets', label: 'Assets', icon: ImagePlus },
    { id: 'music', label: 'Music', icon: Music },
  ] as const
  let selected = 'overview'
  const view = render(
    <StoryLabNavigation
      tabs={[...tabs]}
      activeTab={selected}
      onChange={tab => { selected = tab }}
      notes={<p>Desktop guidance</p>}
    />,
  )

  const navigation = screen.getByRole('navigation', { name: 'Story Lab sections' })
  assert.match(navigation.className, /w-full/)
  assert.match(navigation.className, /overflow-x-auto/)
  assert.match(navigation.className, /md:flex-col/)
  assert.match(navigation.className, /md:overflow-y-auto/)
  assert.equal(screen.getAllByRole('button').length, tabs.length)
  assert.equal(screen.getByRole('button', { name: 'Story' }).getAttribute('aria-current'), 'page')
  assert.equal(screen.getByText('Desliza para más secciones').getAttribute('aria-hidden'), 'true')
  assert.match(screen.getByText('Desktop guidance').parentElement?.className || '', /hidden/)

  fireEvent.click(screen.getByRole('button', { name: 'Music' }))
  assert.equal(selected, 'music')
  view.rerender(
    <StoryLabNavigation
      tabs={[...tabs]}
      activeTab={selected}
      onChange={tab => { selected = tab }}
      notes={<p>Desktop guidance</p>}
    />,
  )
  assert.equal(screen.getByRole('button', { name: 'Music' }).getAttribute('aria-current'), 'page')
  cleanup()
})

test('Story Lab relationships tab is extracted and keeps its review chrome', async () => {
  const { readFileSync } = await import('node:fs')
  const panel = readFileSync(new URL('../src/features/stories/StoryLabPanel.tsx', import.meta.url), 'utf8')
  const tab = readFileSync(new URL('../src/features/stories/StoryRelationshipsTab.tsx', import.meta.url), 'utf8')
  const chrome = readFileSync(new URL('../src/features/stories/storyLabChrome.tsx', import.meta.url), 'utf8')

  assert.match(panel, /import \{ StoryRelationshipsTab \} from '\.\/StoryRelationshipsTab'/)
  assert.match(panel, /from '\.\/storyLabChrome'/)
  assert.match(panel, /id: 'relationships'/)
  assert.match(panel, /\{tab === 'relationships' && \(/)
  assert.match(panel, /<StoryRelationshipsTab/)
  assert.equal(panel.includes('id="story-review-relationships"'), false)
  assert.equal(panel.includes('function RelationshipEditor'), false)
  assert.equal(panel.includes('function SectionHeader'), false)
  assert.match(chrome, /export function SectionHeader/)
  assert.match(tab, /id="story-review-relationships"/)
  assert.match(tab, /Conflict and change often live between characters, not inside isolated biographies\./)
  assert.match(tab, /function RelationshipEditor/)
  assert.match(tab, /scope="relationships"/)

  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { StoryRelationshipsTab } = await import('../src/features/stories/StoryRelationshipsTab.tsx')
  const { createStoryProject } = await import('../src/features/stories/model.ts')
  const character = (id: string, name: string) => ({
    id, name, role: '', age: '', pronouns: '', personality: '', desire: '', need: '',
    flaw: '', conflict: '', arc: '', voice: '', appearance: '', wardrobe: '',
    visualPrompt: '', negativePrompt: '', referenceAssetIds: [], approval: 'draft' as const,
  })
  let project = createStoryProject('full_story')
  project = {
    ...project,
    characters: [character('c1', 'Ada'), character('c2', 'Ben')],
    relationships: [{
      id: 'rel-1', fromCharacterId: 'c1', toCharacterId: 'c2',
      label: 'Rivals', dynamic: 'They compete', evolution: '',
    }],
  }
  const generated: string[] = []
  const approved: string[] = []
  const view = render(
    <StoryRelationshipsTab
      project={project}
      update={updater => { project = updater(structuredClone(project)) }}
      busy={null}
      instruction=""
      setInstruction={() => {}}
      generate={scope => { generated.push(scope) }}
      approve={key => { approved.push(key) }}
      isApproved={() => false}
    />,
  )

  assert.ok(document.getElementById('story-review-relationships'))
  assert.ok(screen.getByRole('heading', { name: 'Relationships' }))
  fireEvent.click(screen.getByRole('button', { name: /Generate text/ }))
  fireEvent.click(screen.getByRole('button', { name: /^Approve$/ }))
  assert.deepEqual(generated, ['relationships'])
  assert.deepEqual(approved, ['relationships'])
  assert.equal(screen.getByDisplayValue('Rivals').tagName, 'INPUT')
  fireEvent.click(screen.getByRole('button', { name: /Relationship/ }))
  view.rerender(
    <StoryRelationshipsTab
      project={project}
      update={updater => { project = updater(structuredClone(project)) }}
      busy={null}
      instruction=""
      setInstruction={() => {}}
      generate={scope => { generated.push(scope) }}
      approve={key => { approved.push(key) }}
      isApproved={() => false}
    />,
  )
  assert.equal(project.relationships.length, 2)
  cleanup()
})

test('Story Lab world tab is extracted and keeps its review chrome', async () => {
  const { readFileSync } = await import('node:fs')
  const panel = readFileSync(new URL('../src/features/stories/StoryLabPanel.tsx', import.meta.url), 'utf8')
  const tab = readFileSync(new URL('../src/features/stories/StoryWorldTab.tsx', import.meta.url), 'utf8')
  const chrome = readFileSync(new URL('../src/features/stories/storyLabChrome.tsx', import.meta.url), 'utf8')

  assert.match(panel, /import \{ StoryWorldTab \} from '\.\/StoryWorldTab'/)
  assert.match(panel, /from '\.\/storyLabChrome'/)
  assert.match(panel, /id: 'world'/)
  assert.match(panel, /\{tab === 'world' && \(/)
  assert.match(panel, /<StoryWorldTab/)
  assert.equal(panel.includes('World bible'), false)
  assert.match(panel, /id="story-review-world"/)
  assert.match(chrome, /export function SectionHeader/)
  assert.match(tab, /id="story-review-world"/)
  assert.match(tab, /Rules, places and a visual language that every production can reuse\./)
  assert.match(tab, /scope="world"/)
  assert.match(tab, /Generate world concept/)

  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { StoryWorldTab } = await import('../src/features/stories/StoryWorldTab.tsx')
  const { createStoryProject } = await import('../src/features/stories/model.ts')
  let project = createStoryProject('full_story')
  project = {
    ...project,
    world: {
      ...project.world,
      summary: 'A rain-soaked port city',
      visualLanguage: 'Sodium light and wet asphalt',
      visualPrompt: 'Cinematic harbor at night',
      locations: [{
        id: 'loc-1', name: 'Harbor', purpose: 'Arrival', description: '', visualPrompt: '', negativePrompt: '', referenceAssetIds: [],
      }],
    },
  }
  const generated: string[] = []
  const approved: string[] = []
  const visuals: Array<{ kind: string; prompt: string }> = []
  const uploads: Array<{ kind: string; id?: string }> = []
  const clicks: string[] = []
  const uploadRef = {
    current: { click: () => { clicks.push('upload') } },
  } as unknown as React.RefObject<HTMLInputElement | null>
  const view = render(
    <StoryWorldTab
      project={project}
      patch={patch => { project = { ...project, ...patch, world: patch.world ? { ...project.world, ...patch.world } : project.world } }}
      update={updater => { project = updater(structuredClone(project)) }}
      busy={null}
      instruction=""
      setInstruction={() => {}}
      generate={scope => { generated.push(scope) }}
      approve={key => { approved.push(key) }}
      isApproved={() => false}
      imageBusy=""
      referenceBatchBusy={false}
      generateVisual={(target, prompt) => { visuals.push({ kind: target.kind, prompt }) }}
      setUploadTarget={target => { uploads.push(target) }}
      uploadRef={uploadRef}
      removeReference={() => {}}
      ReferenceGallery={() => <div>World references</div>}
      LocationEditor={({ location }) => <div>{location.name}</div>}
    />,
  )

  assert.ok(document.getElementById('story-review-world'))
  assert.ok(screen.getByRole('heading', { name: 'World bible' }))
  assert.ok(screen.getByText('Harbor'))
  fireEvent.click(screen.getByRole('button', { name: /Generate text/ }))
  fireEvent.click(screen.getByRole('button', { name: /^Approve$/ }))
  fireEvent.click(screen.getByRole('button', { name: /Generate world concept/ }))
  fireEvent.click(screen.getByRole('button', { name: /Add reference/ }))
  assert.deepEqual(generated, ['world'])
  assert.deepEqual(approved, ['world'])
  assert.deepEqual(visuals, [{ kind: 'world', prompt: 'Cinematic harbor at night' }])
  assert.deepEqual(uploads, [{ kind: 'world' }])
  assert.deepEqual(clicks, ['upload'])
  fireEvent.click(screen.getByRole('button', { name: /Location/ }))
  view.rerender(
    <StoryWorldTab
      project={project}
      patch={patch => { project = { ...project, ...patch, world: patch.world ? { ...project.world, ...patch.world } : project.world } }}
      update={updater => { project = updater(structuredClone(project)) }}
      busy={null}
      instruction=""
      setInstruction={() => {}}
      generate={scope => { generated.push(scope) }}
      approve={key => { approved.push(key) }}
      isApproved={() => false}
      imageBusy=""
      referenceBatchBusy={false}
      generateVisual={(target, prompt) => { visuals.push({ kind: target.kind, prompt }) }}
      setUploadTarget={target => { uploads.push(target) }}
      uploadRef={uploadRef}
      removeReference={() => {}}
      ReferenceGallery={() => <div>World references</div>}
      LocationEditor={({ location }) => <div>{location.name}</div>}
    />,
  )
  assert.equal(project.world.locations.length, 2)
  assert.equal(project.world.locations[1]?.name, 'New location')
  cleanup()
})
