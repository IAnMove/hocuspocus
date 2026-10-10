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
    KeyboardEvent: dom.window.KeyboardEvent,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

type FetchCall = { url: string; init?: RequestInit }

function mockFetch(reply: (url: string, init?: RequestInit) => unknown): { calls: FetchCall[]; restore: () => void } {
  const original = globalThis.fetch
  const calls: FetchCall[] = []
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    calls.push({ url, init })
    return new Response(JSON.stringify(reply(url, init) ?? {}), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch
  return { calls, restore: () => { globalThis.fetch = original } }
}

const body = (call: FetchCall | undefined) => JSON.parse(String(call?.init?.body))

function dubbedEpisode() {
  return {
    id: 'ep1', title: 'Piloto', shots: [
      { id: 's0', dialogueBeats: [], layout2d: { card: { kind: 'title', title: 'VALLE', body: 'Episodio 1' } } },
      { id: 's1', dialogueBeats: [{ id: 'b1', characterId: 'kevin', text: 'Vale, Gary.' }, { id: 'b2', characterId: 'gary', text: '¡Hola!' },
        { id: 'b3', characterId: 'gary', text: 'Adiós.' }] },
    ],
    languageVersions: { english: {
      title: 'Pilot', dialogue: { b1: 'Okay, Gary.', b2: 'Hi!' }, cards: { s0: { title: 'VALLEY', body: 'Episode 1' } },
      approvedAttemptIds: {}, assemblyAssetIds: [],
      machineTranslated: { dialogue: ['b1', 'b2'], cards: ['s0'], title: true, requestedBy: 'agent' },
    } },
  }
}

test('machine-translation marks count only the texts a version still has, and checking them sends them as they are', async () => {
  const { checkedWrite, episodeCards, machineMarks } = await import('../src/features/series/languageVersionMarks.ts')
  const version = { ...dubbedEpisode().languageVersions.english, machineTranslated: { dialogue: ['b1', 'ghost'], cards: ['s0', 's9'], title: true } }
  const marks = machineMarks(version as never)
  assert.deepEqual([[...marks.lines], [...marks.cards], marks.title, marks.count], [['b1'], ['s0'], true, 3])
  assert.deepEqual(checkedWrite(version as never, marks), {
    dialogue: { b1: 'Okay, Gary.' }, cards: { s0: { title: 'VALLEY', body: 'Episode 1' } }, title: 'Pilot' })
  assert.equal(machineMarks(undefined).count, 0)
  assert.deepEqual(episodeCards(dubbedEpisode() as never), [{ shotId: 's0', title: 'VALLE', body: 'Episodio 1' }])
})

test('Series Lab shows machine translations per line and card, and a person checking one clears it', async () => {
  const { render, screen, cleanup, fireEvent, waitFor } = await import('@testing-library/react')
  const { SeriesLanguageVersions } = await import('../src/features/series/SeriesLanguageVersions.tsx')
  const { useSeriesStore } = await import('../src/features/series/store.ts')
  let reloads = 0
  useSeriesStore.setState({ reload: async () => { reloads += 1 } })
  const fetched = mockFetch(() => ({ revision: 2, language: 'english', version: null, missingLines: ['b3'] }))
  try {
    render(<SeriesLanguageVersions workspace="uv" series={{ id: 'uv', spokenLanguage: 'Español', language: 'Español' } as never}
      episode={dubbedEpisode() as never} />)
    assert.ok(screen.getByTestId('series-machine-translation').textContent?.includes('4 texts in this version are machine translations, asked for by an agent (MCP)'))
    assert.ok(document.querySelector('[data-machine-translated="b1"]') && document.querySelector('[data-machine-translated="b2"]'))
    assert.ok(document.querySelector('[data-machine-translated="s0"]') && document.querySelector('[data-machine-translated="title"]'))
    assert.equal(document.querySelector('[data-machine-translated="b3"]'), null, 'an untranslated line has no mark')
    assert.equal((screen.getByLabelText('Card title of s0') as HTMLInputElement).value, 'VALLEY')
    fireEvent.click(screen.getByLabelText('Mark b1 as checked'))
    await waitFor(() => assert.ok(screen.getByText('Marked as checked by you.')))
    assert.equal(fetched.calls[0].url, '/api/v1/series/uv/episodes/ep1/language-versions/english')
    assert.equal(fetched.calls[0].init?.method, 'PUT')
    assert.deepEqual(body(fetched.calls[0]), { workspace: 'uv', version: { dialogue: { b1: 'Okay, Gary.' } } })
    fireEvent.change(screen.getByLabelText('Translation of b2'), { target: { value: 'Hey!' } })
    assert.equal(document.querySelector('[data-machine-translated="b2"]'), null, 'an edited line shows as the person’s')
    fireEvent.click(screen.getByText('Save lines'))
    await waitFor(() => assert.equal(fetched.calls.length, 2))
    assert.deepEqual(body(fetched.calls[1]).version, { dialogue: { b2: 'Hey!' } })
    fireEvent.click(screen.getByText('Mark all as checked'))
    await waitFor(() => assert.equal(fetched.calls.length, 3))
    assert.deepEqual(body(fetched.calls[2]).version, {
      dialogue: { b1: 'Okay, Gary.', b2: 'Hi!' }, cards: { s0: { title: 'VALLEY', body: 'Episode 1' } }, title: 'Pilot' })
    await waitFor(() => assert.equal(reloads, 3))
  } finally {
    cleanup()
    fetched.restore()
  }
})

test('the Episode tab lists the scripts an agent sent, shows and downloads one, and rewrites the episode from it', async () => {
  const { render, screen, cleanup, fireEvent, waitFor } = await import('@testing-library/react')
  const { SeriesEpisodeScripts } = await import('../src/features/series/SeriesEpisodeScripts.tsx')
  const revisions = [
    { revision: 2, submittedAt: '2026-10-06T10:00:00Z', by: 'agent', tool: 'series.episode.from_script', created: false, shots: 14,
      languages: ['spanish', 'english'], digest: 'b', applied: 2 },
    { revision: 1, submittedAt: '2026-10-05T10:00:00Z', by: 'agent', tool: 'series.episode.from_script', created: true, shots: 12,
      languages: ['spanish'], digest: 'a', applied: 1 },
  ]
  const script = { title: { es: 'La confesión' }, shots: [{ scene: 'open' }] }
  const fetched = mockFetch((url, init) => {
    if (url.endsWith('/rewrite')) return body({ url, init }).check ? { checked: true, shots: ['e1s00'] } : { episodeId: 'ep1', scriptRevision: 3 }
    if (url.includes('/scripts/1?')) return { ...revisions[1], script }
    return { revisions, total: 2 }
  })
  let saved = 0, reloaded = 0
  try {
    render(<SeriesEpisodeScripts workspace="pu" series={{ id: 'pu-es' } as never} episode={{ id: 'ep1' } as never}
      saveNow={async () => { saved += 1 }} reload={async () => { reloaded += 1 }} />)
    await waitFor(() => assert.ok(screen.getByTestId('series-script-2')))
    assert.equal(fetched.calls[0].url, '/api/v1/series/pu-es/episodes/ep1/scripts?workspace=pu')
    const first = screen.getByTestId('series-script-1')
    assert.ok(first.textContent?.includes('by an agent (MCP)') && first.textContent.includes('12 shots') && first.textContent.includes('created the episode'))
    assert.ok(screen.getByTestId('series-script-2').textContent?.includes('written 2 times'))
    assert.equal(first.querySelector('a[download]')?.getAttribute('href'), '/api/v1/series/pu-es/episodes/ep1/scripts/1?workspace=pu&download=true')
    fireEvent.click(first.querySelector('button[aria-pressed]') as HTMLElement)
    await waitFor(() => assert.ok(screen.getByTestId('series-script-viewer').textContent?.includes('"La confesión"')))
    fireEvent.click(first.querySelectorAll('button')[1] as HTMLElement)
    fireEvent.click(screen.getByText('Rewrite'))
    await waitFor(() => assert.ok(screen.getByText('Episode rewritten from revision 1 (now revision 3).')))
    const rewrites = fetched.calls.filter(call => call.url.endsWith('/scripts/1/rewrite'))
    assert.deepEqual(rewrites.map(call => body(call)), [{ workspace: 'pu', check: true }, { workspace: 'pu', check: false }])
    assert.deepEqual([saved, reloaded], [1, 1])
  } finally {
    cleanup()
    fetched.restore()
  }
})

test('a rewrite whose script no longer fits the series shows its problems and writes nothing', async () => {
  const { render, screen, cleanup, fireEvent, waitFor } = await import('@testing-library/react')
  const { SeriesEpisodeScripts } = await import('../src/features/series/SeriesEpisodeScripts.tsx')
  const original = globalThis.fetch
  const posted: string[] = []
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === 'POST') {
      posted.push(String(init.body))
      return new Response(JSON.stringify({ detail: { code: 'invalid_script', message: 'shot 0: unknown character kevin', problems: ['shot 0: unknown character kevin'] } }), { status: 400 })
    }
    return new Response(JSON.stringify({ revisions: [{ revision: 1, submittedAt: '2026-10-05T10:00:00Z', by: 'wizard', created: true, shots: 1, languages: [], applied: 1 }] }))
  }) as typeof fetch
  try {
    render(<SeriesEpisodeScripts workspace="pu" series={{ id: 'pu-es' } as never} episode={{ id: 'ep1' } as never}
      saveNow={async () => undefined} reload={async () => undefined} />)
    await waitFor(() => assert.ok(screen.getByText('by the Wizard')))
    fireEvent.click(screen.getByText('Rewrite from this script'))
    fireEvent.click(screen.getByText('Rewrite'))
    await waitFor(() => assert.ok(screen.getByRole('alert').textContent?.includes('unknown character kevin')))
    assert.equal(posted.length, 1, 'only the check ran')
  } finally {
    cleanup()
    globalThis.fetch = original
  }
})

test('a music production card links the page it was published as', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { PublishedPageLink } = await import('../src/features/music-productions/PublishedPageLink.tsx')
  try {
    render(<PublishedPageLink publication={{ page: 'http://lan.local:8844/homage-1a/homage.html', mode: 'preview', published_by: 'agent', count: 2 }} />)
    const link = screen.getByText('Review preview page').closest('a')
    assert.equal(link?.getAttribute('href'), 'http://lan.local:8844/homage-1a/homage.html')
    assert.equal(link?.getAttribute('target'), '_blank')
    assert.ok(link?.getAttribute('rel')?.includes('noopener'))
    assert.ok(screen.getByTestId('music-production-publication').textContent?.includes('Published by an agent (MCP)'))
    assert.ok(screen.getByTestId('music-production-publication').textContent?.includes('2 publications'))
    cleanup()
    render(<PublishedPageLink publication={{ page: 'javascript:alert(1)', mode: 'release' }} />)
    assert.equal(document.querySelector('[data-testid="music-production-publication"]'), null)
  } finally {
    cleanup()
  }
})

test('the music productions list shows the published page beside the open button', async () => {
  const { render, screen, cleanup, waitFor } = await import('@testing-library/react')
  const { MusicProductionsPanel } = await import('../src/features/music-productions/MusicProductionsPanel.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  useStore.setState({ activeWorkspace: 'film' })
  const fetched = mockFetch(() => ({ productions: [{ production_id: 'show', status: 'completed', title: 'Night bus', duration: 20,
    contact_sheet: null, montage: null, video: null, editable: null,
    publication: { page: 'http://127.0.0.1:8844/show-1/show.html', mode: 'release', published_by: 'user', count: 1 } }] }))
  try {
    render(<MusicProductionsPanel onClose={() => undefined} />)
    await waitFor(() => assert.ok(screen.getByText('Published page')))
    const card = screen.getByTestId('music-production-show')
    assert.ok(card.querySelector('button')?.textContent?.includes('Night bus'))
    assert.equal(card.querySelector('a')?.getAttribute('href'), 'http://127.0.0.1:8844/show-1/show.html')
    assert.equal(card.querySelector('button a'), null, 'the link is not inside the open button')
  } finally {
    cleanup()
    fetched.restore()
  }
})

test('Made by agents asks the listing for agent work and badges it without loading sidecars', async () => {
  const { galleryListQuery, GALLERY_LIST_FILTERS } = await import('../src/lib/galleryListQuery.ts')
  const { categoryForMediaFilter } = await import('../src/lib/navigationCategories.ts')
  const { listedMaker } = await import('../src/lib/outputProvenance.ts')
  const query = galleryListQuery('agents')
  assert.equal(query.origin, 'agent')
  assert.equal(query.useServerList, true)
  assert.equal(galleryListQuery('all').origin, undefined)
  assert.ok(GALLERY_LIST_FILTERS.has('agents'))
  assert.equal(categoryForMediaFilter('agents'), 'media')
  assert.deepEqual(listedMaker({ actor: 'agent', capability: 'generation.image' }), { origin: 'agent', capability: 'generation.image' })
  assert.deepEqual(listedMaker({ actor: 'wizard' }), { origin: 'wizard', capability: '' })
  assert.equal(listedMaker(null), null)

  const { fetchOutputs } = await import('../src/api/outputs.ts')
  const fetched = mockFetch(() => ({ outputs: [{ name: 'a.png', type: 'image', origin: { actor: 'agent', capability: 'generation.image' } }], total: 1 }))
  try {
    const listed = await fetchOutputs(100, 0, { workspace: 'pu', origin: 'agent' })
    assert.ok(fetched.calls[0].url.includes('origin=agent'))
    assert.deepEqual(listed.outputs[0].origin, { actor: 'agent', capability: 'generation.image' })
  } finally {
    fetched.restore()
  }
})

test('the gallery keeps the listing origin, filters by it and badges grid tiles', async () => {
  const { render, cleanup } = await import('@testing-library/react')
  const { useStore } = await import('../src/stores/useStore.ts')
  const { GalleryTile } = await import('../src/components/MainContent/GalleryTile.tsx')
  const outputs = [
    { name: 'agent.png', url: '/a', type: 'image', mode: null, favorite: false, size: 1, created_at: 2, origin: { actor: 'agent', capability: 'generation.image' } },
    { name: 'mine.png', url: '/m', type: 'image', mode: null, favorite: false, size: 1, created_at: 1 },
  ]
  const fetched = mockFetch(() => ({ outputs, total: 2 }))
  try {
    useStore.setState({ activeWorkspace: 'pu', mediaFilter: 'all', outputSearchQuery: '' })
    await useStore.getState().loadOutputs()
    assert.deepEqual(useStore.getState().outputs.map(file => file.origin?.actor ?? null), ['agent', null])
    useStore.setState({ mediaFilter: 'agents' })
    assert.deepEqual(useStore.getState().filteredOutputs().map(file => file.name), ['agent.png'])
    await useStore.getState().loadOutputs()
    const listing = fetched.calls.filter(call => call.url.startsWith('/api/v1/outputs?')).at(-1)
    assert.ok(listing?.url.includes('origin=agent'), listing?.url)
    assert.ok(listing?.url.includes('limit=100'), 'agent work pages like the full list')
    render(<GalleryTile file={outputs[0] as never} workspace="pu" index={0} active={false} cover top={0} left={0} width={120} height={120}
      selecting={false} picked={false} onOpen={() => undefined} onOpenDetails={() => undefined} onPick={() => undefined} onLongPress={() => undefined} />)
    assert.equal(document.querySelector('[data-origin="agent"]')?.textContent, 'Agent (MCP)')
  } finally {
    cleanup()
    fetched.restore()
    useStore.setState({ mediaFilter: 'all' })
  }
})
