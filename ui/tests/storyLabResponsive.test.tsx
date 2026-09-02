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
    HTMLInputElement: dom.window.HTMLInputElement,
    HTMLTextAreaElement: dom.window.HTMLTextAreaElement,
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

function sectionHandlers(projectRef: { current: import('../src/features/stories/types').StoryProject }) {
  const generated: string[] = []
  const approved: string[] = []
  return {
    generated,
    approved,
    props: {
      update: (updater: (project: typeof projectRef.current) => typeof projectRef.current) => {
        projectRef.current = updater(structuredClone(projectRef.current))
      },
      busy: null,
      instruction: '',
      setInstruction: () => {},
      generate: (scope: string) => { generated.push(scope) },
      approve: (key: string) => { approved.push(key) },
      isApproved: () => false,
    },
  }
}

function sampleCharacter(id: string, name: string) {
  return {
    id, name, role: 'Lead', age: '', pronouns: '', personality: '', desire: '', need: '',
    flaw: '', conflict: '', arc: '', voice: '', appearance: '', wardrobe: '',
    visualPrompt: 'Portrait of Ada', negativePrompt: '', referenceAssetIds: [] as string[], approval: 'draft' as const,
  }
}

test('Story Lab panel uses shared editors instead of passing component props', async () => {
  const { readFileSync } = await import('node:fs')
  const panel = readFileSync(new URL('../src/features/stories/StoryLabPanel.tsx', import.meta.url), 'utf8')
  const world = readFileSync(new URL('../src/features/stories/StoryWorldTab.tsx', import.meta.url), 'utf8')
  const characters = readFileSync(new URL('../src/features/stories/StoryCharactersTab.tsx', import.meta.url), 'utf8')
  const structure = readFileSync(new URL('../src/features/stories/StoryStructureTab.tsx', import.meta.url), 'utf8')
  const chrome = readFileSync(new URL('../src/features/stories/storyLabChrome.tsx', import.meta.url), 'utf8')

  assert.match(panel, /import \{ StoryLabVisualsProvider \} from '\.\/StoryLabVisualsProvider'/)
  assert.match(panel, /import \{ ReferenceGallery \} from '\.\/ReferenceGallery'/)
  assert.match(panel, /import \{ LocationEditor \} from '\.\/LocationEditor'/)
  assert.match(panel, /import \{ StoryCharactersTab \} from '\.\/StoryCharactersTab'/)
  assert.match(panel, /import \{ StoryStructureTab \} from '\.\/StoryStructureTab'/)
  assert.equal(panel.includes('function ReferenceGallery'), false)
  assert.equal(panel.includes('function LocationEditor'), false)
  assert.equal(panel.includes('function CharacterEditor'), false)
  assert.equal(panel.includes('function BeatEditor'), false)
  assert.equal(panel.includes('ReferenceGallery={'), false)
  assert.equal(panel.includes('LocationEditor={'), false)
  assert.match(chrome, /export function SectionHeader/)
  assert.match(world, /id="story-review-world"/)
  assert.match(world, /useStoryLabVisuals/)
  assert.match(characters, /id="story-review-characters"/)
  assert.match(structure, /id="story-review-structure"/)
})

test('Story Lab relationships tab is extracted and keeps its review chrome', async () => {
  const { readFileSync } = await import('node:fs')
  const panel = readFileSync(new URL('../src/features/stories/StoryLabPanel.tsx', import.meta.url), 'utf8')
  const tab = readFileSync(new URL('../src/features/stories/StoryRelationshipsTab.tsx', import.meta.url), 'utf8')

  assert.match(panel, /<StoryRelationshipsTab/)
  assert.equal(panel.includes('id="story-review-relationships"'), false)
  assert.equal(panel.includes('function RelationshipEditor'), false)
  assert.match(tab, /t\('relationships.description'\)/)
  assert.match(tab, /scope="relationships"/)

  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { StoryRelationshipsTab } = await import('../src/features/stories/StoryRelationshipsTab.tsx')
  const { createStoryProject } = await import('../src/features/stories/model.ts')
  const projectRef = {
    current: {
      ...createStoryProject('full_story'),
      characters: [sampleCharacter('c1', 'Ada'), sampleCharacter('c2', 'Ben')],
      relationships: [{
        id: 'rel-1', fromCharacterId: 'c1', toCharacterId: 'c2',
        label: 'Rivals', dynamic: 'They compete', evolution: '',
      }],
    },
  }
  const handlers = sectionHandlers(projectRef)
  const view = render(
    <StoryRelationshipsTab project={projectRef.current} {...handlers.props} />,
  )

  assert.ok(document.getElementById('story-review-relationships'))
  assert.ok(screen.getByRole('heading', { name: 'Relationships' }))
  fireEvent.click(screen.getByRole('button', { name: /Generate text/ }))
  fireEvent.click(screen.getByRole('button', { name: /^Approve$/ }))
  assert.deepEqual(handlers.generated, ['relationships'])
  assert.deepEqual(handlers.approved, ['relationships'])
  assert.equal(screen.getByDisplayValue('Rivals').tagName, 'INPUT')
  fireEvent.click(screen.getByRole('button', { name: /Relationship/ }))
  view.rerender(
    <StoryRelationshipsTab project={projectRef.current} {...handlers.props} />,
  )
  assert.equal(projectRef.current.relationships.length, 2)
  cleanup()
})

test('Story Lab world tab uses the shared visuals controller', async () => {
  const { readFileSync } = await import('node:fs')
  const panel = readFileSync(new URL('../src/features/stories/StoryLabPanel.tsx', import.meta.url), 'utf8')
  const tab = readFileSync(new URL('../src/features/stories/StoryWorldTab.tsx', import.meta.url), 'utf8')
  assert.match(panel, /<StoryWorldTab/)
  assert.equal(panel.includes('World bible'), false)
  assert.match(tab, /t\('world.generateConcept'\)/)
  assert.equal(tab.includes('ReferenceGallery:'), false)

  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { StoryWorldTab } = await import('../src/features/stories/StoryWorldTab.tsx')
  const { StoryLabVisualsProvider } = await import('../src/features/stories/StoryLabVisualsProvider.tsx')
  const { createStoryProject } = await import('../src/features/stories/model.ts')
  const projectRef = {
    current: {
      ...createStoryProject('full_story'),
      world: {
        ...createStoryProject('full_story').world,
        summary: 'A rain-soaked port city',
        visualLanguage: 'Sodium light and wet asphalt',
        visualPrompt: 'Cinematic harbor at night',
        locations: [{
          id: 'loc-1', name: 'Harbor', purpose: 'Arrival', description: '', visualPrompt: '', negativePrompt: '', referenceAssetIds: [],
        }],
      },
    },
  }
  const handlers = sectionHandlers(projectRef)
  const visuals: Array<{ kind: string; prompt: string }> = []
  const uploads: Array<{ kind: string; id?: string }> = []
  const wrap = (node: React.ReactNode) => (
    <StoryLabVisualsProvider value={{
      imageBusy: '',
      referenceBatchBusy: false,
      generateVisual: (target, prompt) => { visuals.push({ kind: target.kind, prompt }) },
      requestUpload: target => { uploads.push(target) },
      removeReference: () => {},
    }}>
      {node}
    </StoryLabVisualsProvider>
  )
  const view = render(wrap(
    <StoryWorldTab
      project={projectRef.current}
      patch={patch => {
        projectRef.current = {
          ...projectRef.current,
          ...patch,
          world: patch.world ? { ...projectRef.current.world, ...patch.world } : projectRef.current.world,
        }
      }}
      {...handlers.props}
    />,
  ))

  assert.ok(document.getElementById('story-review-world'))
  assert.ok(screen.getByRole('heading', { name: 'World bible' }))
  assert.ok(screen.getByDisplayValue('Harbor'))
  fireEvent.click(screen.getByRole('button', { name: /Generate text/ }))
  fireEvent.click(screen.getByRole('button', { name: /^Approve$/ }))
  fireEvent.click(screen.getByRole('button', { name: /Generate world concept/ }))
  fireEvent.click(screen.getAllByRole('button', { name: /^Add reference$/ })[0])
  assert.deepEqual(handlers.generated, ['world'])
  assert.deepEqual(handlers.approved, ['world'])
  assert.deepEqual(visuals, [{ kind: 'world', prompt: 'Cinematic harbor at night' }])
  assert.deepEqual(uploads, [{ kind: 'world' }])
  fireEvent.click(screen.getByRole('button', { name: /^Location$/ }))
  view.rerender(wrap(
    <StoryWorldTab
      project={projectRef.current}
      patch={patch => {
        projectRef.current = {
          ...projectRef.current,
          ...patch,
          world: patch.world ? { ...projectRef.current.world, ...patch.world } : projectRef.current.world,
        }
      }}
      {...handlers.props}
    />,
  ))
  assert.equal(projectRef.current.world.locations.length, 2)
  assert.equal(projectRef.current.world.locations[1]?.name, 'New location')
  cleanup()
})

test('Story Lab characters tab is extracted with i18n chrome', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { StoryCharactersTab } = await import('../src/features/stories/StoryCharactersTab.tsx')
  const { StoryLabVisualsProvider } = await import('../src/features/stories/StoryLabVisualsProvider.tsx')
  const { createStoryProject } = await import('../src/features/stories/model.ts')
  const projectRef = {
    current: {
      ...createStoryProject('full_story'),
      characters: [sampleCharacter('c1', 'Ada')],
    },
  }
  const handlers = sectionHandlers(projectRef)
  const visuals: Array<{ kind: string; id?: string }> = []
  const view = render(
    <StoryLabVisualsProvider value={{
      imageBusy: '',
      referenceBatchBusy: false,
      generateVisual: target => { visuals.push(target) },
      requestUpload: () => {},
      removeReference: () => {},
    }}>
      <StoryCharactersTab project={projectRef.current} {...handlers.props} />
    </StoryLabVisualsProvider>,
  )

  assert.ok(document.getElementById('story-review-characters'))
  assert.ok(document.getElementById('story-review-character-c1'))
  assert.ok(screen.getByRole('heading', { name: 'Characters' }))
  fireEvent.click(screen.getByRole('button', { name: /Generate text/ }))
  fireEvent.click(screen.getByRole('button', { name: /^Approve$/ }))
  fireEvent.click(screen.getByRole('button', { name: /Generate first identity/ }))
  assert.deepEqual(handlers.generated, ['characters'])
  assert.deepEqual(handlers.approved, ['characters'])
  assert.deepEqual(visuals, [{ kind: 'character', id: 'c1' }])
  fireEvent.click(screen.getByRole('button', { name: /^Character$/ }))
  view.rerender(
    <StoryLabVisualsProvider value={{
      imageBusy: '',
      referenceBatchBusy: false,
      generateVisual: target => { visuals.push(target) },
      requestUpload: () => {},
      removeReference: () => {},
    }}>
      <StoryCharactersTab project={projectRef.current} {...handlers.props} />
    </StoryLabVisualsProvider>,
  )
  assert.equal(projectRef.current.characters.length, 2)
  assert.equal(projectRef.current.characters[1]?.name, 'New character')
  cleanup()
})

test('Story Lab structure tab is extracted with i18n chrome', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { StoryStructureTab } = await import('../src/features/stories/StoryStructureTab.tsx')
  const { createStoryProject } = await import('../src/features/stories/model.ts')
  const projectRef = {
    current: {
      ...createStoryProject('full_story'),
      beats: [{ id: 'beat-1', stage: 'Act I', title: 'Arrival', summary: 'They meet', goal: '', conflict: '', turn: '' }],
    },
  }
  const handlers = sectionHandlers(projectRef)
  const view = render(
    <StoryStructureTab project={projectRef.current} {...handlers.props} />,
  )

  assert.ok(document.getElementById('story-review-structure'))
  assert.ok(screen.getByRole('heading', { name: 'Dramatic structure' }))
  fireEvent.click(screen.getByRole('button', { name: /Generate text/ }))
  fireEvent.click(screen.getByRole('button', { name: /^Approve$/ }))
  assert.deepEqual(handlers.generated, ['structure'])
  assert.deepEqual(handlers.approved, ['structure'])
  assert.equal(screen.getByDisplayValue('Arrival').tagName, 'INPUT')
  fireEvent.click(screen.getByRole('button', { name: /^Beat$/ }))
  view.rerender(
    <StoryStructureTab project={projectRef.current} {...handlers.props} />,
  )
  assert.equal(projectRef.current.beats.length, 2)
  assert.equal(projectRef.current.beats[1]?.stage, 'New beat')
  cleanup()
})
