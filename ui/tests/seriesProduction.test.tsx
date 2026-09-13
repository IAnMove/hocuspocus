import assert from 'node:assert/strict'
import test from 'node:test'
import React, { useState } from 'react'
import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'
import type { SeriesProject } from '../src/features/series/types'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://192.168.1.87/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
  HTMLElement: dom.window.HTMLElement, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent, MutationObserver: dom.window.MutationObserver })
window.matchMedia = () => ({ matches: false }) as MediaQueryList

function project(): SeriesProject {
  return JSON.parse(readFileSync(new URL('../../docs/series-lab/example-series-library-v1.json', import.meta.url), 'utf8')).seriesById.series_signal
}

test('production checkboxes allow a mix and always retain at least one method', async () => {
  const { render, fireEvent, cleanup } = await import('@testing-library/react')
  const { SeriesProductionMethods } = await import('../src/features/series/SeriesProductionMethods')
  let saved = project()
  function Form() {
    const [series, setSeries] = useState(saved)
    return <SeriesProductionMethods series={series} update={updater => setSeries(current => (saved = updater(current)))} />
  }
  try {
    const view = render(<Form />)
    const boxes = view.getAllByRole('checkbox') as HTMLInputElement[]
    assert.equal(boxes[0].disabled, true)
    fireEvent.click(boxes[1])
    assert.deepEqual(saved.allowedProductionMethods, ['generated_video', 'animation_2d'])
    fireEvent.click(boxes[0])
    assert.deepEqual(saved.allowedProductionMethods, ['animation_2d'])
    assert.equal(boxes[1].disabled, true)
  } finally { cleanup() }
})

test('shot breakdown enables methods and assigns existing empty shots without altering completed or active takes', async t => {
  const { render, fireEvent, cleanup } = await import('@testing-library/react')
  const { SeriesShotsPanel } = await import('../src/features/series/SeriesShotsPanel')
  const { assignSeriesEpisodeMethod } = await import('../src/features/series/productionMethods')
  const { ensureUiI18n } = await import('../src/i18n')
  const translate = ensureUiI18n().getFixedT('en', 'seriesLab')
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ outputs:[], total:0 }))
  t.after(() => { globalThis.fetch = originalFetch; cleanup() })
  let saved = project()
  saved.allowedProductionMethods = ['generated_video']
  const episodeId = Object.keys(saved.episodesById)[0]
  const episode = saved.episodesById[episodeId], template = episode.shots[0]
  const previousAttempt = template.attempts[0]
  episode.shots = ['none', 'failed', 'queued', 'running', 'completed', 'approved', 'cancelling'].map((status, index) => ({
    ...structuredClone(template), id:`shot-${index}`, order:index + 1, productionMethod:'generated_video', dialogueBeats:[],
    approvedAttemptId:status === 'approved' ? `take-${index}` : undefined,
    attempts:status === 'none' ? [] : [{ ...previousAttempt, id:`take-${index}`, status:status === 'approved' ? 'completed' : status }],
  })) as typeof episode.shots
  const originalEpisode = structuredClone(episode)
  const originalCanon = structuredClone(saved.canon)
  assert.equal(assignSeriesEpisodeMethod(saved, episode, 'animation_2d'), episode)
  function Form() {
    const [series, setSeries] = useState(saved)
    const update = (updater: (current: SeriesProject) => SeriesProject) => setSeries(current => (saved = updater(current)))
    return <SeriesShotsPanel workspace="source" series={series} episode={series.episodesById[episodeId]}
      updateSeries={update} updateEpisode={updater => update(current => ({ ...current, episodesById:{ ...current.episodesById,
        [episodeId]:updater(current.episodesById[episodeId]) } }))} replaceSeries={() => {}} saveNow={async () => saved}
      onAcknowledgeLipSync={async () => {}} onRender={() => {}} />
  }
  const view = render(<Form />)
  const animationBox = view.getByRole('checkbox', { name:/2D animation/ })
  fireEvent.click(animationBox)
  assert.deepEqual(saved.allowedProductionMethods, ['generated_video', 'animation_2d'])
  assert.ok(saved.episodesById[episodeId].shots.every(shot => shot.productionMethod === 'generated_video'))
  const individual = view.getByRole('combobox', { name:translate('production.shotMethod', {order:1}) }) as HTMLSelectElement
  assert.ok([...individual.options].some(option => option.value === 'animation_2d'))
  const bulk = view.getByRole('combobox', { name:translate('production.bulkMethod') }) as HTMLSelectElement
  fireEvent.change(bulk, {target:{value:'animation_2d'}})
  fireEvent.click(view.getByRole('button', { name:translate('production.bulkApply', {count:2}) }))
  const updated = saved.episodesById[episodeId]
  assert.deepEqual(updated.shots.slice(0, 2).map(shot => shot.productionMethod), ['animation_2d','animation_2d'])
  assert.deepEqual(updated.shots.slice(2), originalEpisode.shots.slice(2))
  assert.deepEqual(updated.shots[1].attempts, originalEpisode.shots[1].attempts)
  assert.deepEqual(updated.script, originalEpisode.script)
  assert.deepEqual(updated.canonSnapshot, originalEpisode.canonSnapshot)
  assert.deepEqual(saved.canon, originalCanon)
  assert.equal((view.getByRole('button', { name:translate('production.bulkApply', {count:0}) }) as HTMLButtonElement).disabled, true)
  fireEvent.click(animationBox)
  assert.equal(bulk.value, '')
  assert.equal((view.getByRole('button', { name:translate('production.bulkApply', {count:2}) }) as HTMLButtonElement).disabled, true)
})

test('character and location image jobs attach to their source workspace and can reconnect without another submission', async t => {
  const { generateSeriesReferenceImage, pendingSeriesImage, seriesImageJobKey, seriesReferencePrompt } = await import('../src/features/series/referenceImages')
  const { useStore } = await import('../src/stores/useStore')
  const originalFetch = globalThis.fetch
  t.after(() => { globalThis.fetch = originalFetch; localStorage.clear() })
  useStore.setState({ activeWorkspace: 'another-workspace' })
  for (const kind of ['character', 'location'] as const) {
    const series = project()
    series.provider = { ...series.provider, useGlobalProfile: false, imageProvider: 'minimax', imageModel: 'image-01' }
    const entity = kind === 'character' ? series.characters[0] : series.locations[0]
    entity.referenceAssetIds = []
    if ('primaryReferenceAssetId' in entity) delete entity.primaryReferenceAssetId
    const target = { kind, id: entity.id }
    const key = seriesImageJobKey('source-workspace', series.id, target)
    const prompt = seriesReferencePrompt(series, target)
    assert.equal(prompt.includes(series.visualStyle), kind === 'character')
    assert.ok(prompt.includes(kind === 'character' ? 'One full-body character' : 'One establishing view'))
    let submitted = 0, imports = 0, prepared = 0
    const json = (value: unknown) => new Response(JSON.stringify(value), { headers: { 'Content-Type':'application/json' } })
    const job = { jobId: `image-${kind}`, status:'completed', workspace:'source-workspace', result:{ asset:{ source:'/reference.png', name:'reference.png', model:'image-01' } } }
    globalThis.fetch = async (input, init) => {
      const path = new URL(String(input), 'http://localhost').pathname
      if (path === '/api/v1/llm/generate') {
        const body = JSON.parse(String(init?.body))
        assert.equal(kind, 'location')
        assert.equal(body.workspace, 'source-workspace')
        assert.equal(JSON.parse(body.prompt).location.name, entity.name)
        prepared += 1
        return json({ text:JSON.stringify({ environment:`Empty ${entity.name}, concrete walls and equipment under soft light.`, renderingStyle:'Flat cutout illustration.' }) })
      }
      if (path === '/api/v1/comics/generate/minimax/jobs') {
        const body = JSON.parse(String(init?.body))
        assert.equal(body.workspace, 'source-workspace')
        if (kind === 'location') {
          assert.ok(body.prompt.startsWith('Empty, unoccupied environment.'))
          assert.ok(!body.prompt.includes(series.visualStyle))
          assert.equal(body.subject_reference, undefined)
          assert.equal(body.aspect_ratio, '16:9')
        }
        submitted += 1
        return json(job)
      }
      if (path === `/api/v1/comics/generate/minimax/jobs/${job.jobId}`) return json(job)
      if (path === '/reference.png') return new Response(new Uint8Array([1]), { headers: { 'Content-Type':'image/png' } })
      if (path === '/api/v1/upload') return json({ path:'/uploads/reference.png', filename:'reference.png', url:'/api/v1/uploads/reference.png' })
      if (path.endsWith('/assets/import')) {
        const body = JSON.parse(String(init?.body))
        assert.equal(body.workspace, 'source-workspace')
        assert.equal(body.ownerId, entity.id)
        assert.equal(body.ownerType, kind)
        assert.equal(body.metadata.jobId, job.jobId)
        imports += 1
        return json({ asset:{ id:'saved-image' }, series })
      }
      throw new Error(`Unexpected request: ${path}`)
    }
    // A reconnect must use the recorded prompt/provider even after a form edit.
    localStorage.setItem(key, JSON.stringify({ jobId:job.jobId, prompt, provider:'minimax', model:'image-01' }))
    await generateSeriesReferenceImage('source-workspace', series, target, { prompt:'Edited after submission', beforeImport:async () => {} })
    assert.equal(submitted, 0)
    assert.equal(prepared, 0)
    assert.equal(imports, 1)
    assert.equal(pendingSeriesImage(key), undefined)
    await generateSeriesReferenceImage('source-workspace', series, target, { prompt, beforeImport:async () => {} })
    assert.equal(submitted, 1)
    assert.equal(prepared, kind === 'location' ? 1 : 0)
    assert.equal(imports, 2)
  }
})

test('location prompt preparation separates occupied descriptions and character style from the image request', async t => {
  const { prepareSeriesLocationPrompt, seriesReferencePrompt, generateSeriesReferenceImage } = await import('../src/features/series/referenceImages')
  const series = project()
  series.visualStyle = 'Cutout 2D, characters with huge heads and short legs, flat bright palette.'
  series.characterVisualStyle = 'Character-only secret wardrobe instructions'
  series.provider = { ...series.provider, useGlobalProfile:false, writingProvider:'minimax', writingModel:'writer-for-series',
    writingBaseUrl:'https://api.minimax.io', imageProvider:'minimax' }
  const location = series.locations[0]
  location.name = 'Open Source Diner'
  location.description = 'Classic diner: red stools, a waitress in an apron, a long counter, round tables with rival developers and an espresso machine shaped like an inference server.'
  const target = { kind:'location' as const, id:location.id }
  const originalFetch = globalThis.fetch
  t.after(() => { globalThis.fetch = originalFetch; localStorage.clear() })
  let calls = 0
  globalThis.fetch = async (input, init) => {
    assert.equal(String(input), '/api/v1/llm/generate')
    const body = JSON.parse(String(init?.body)), brief = JSON.parse(body.prompt)
    assert.equal(body.writingModel, 'writer-for-series')
    assert.equal(body.writingProvider, 'minimax')
    assert.equal(body.workspace, 'location-prompts')
    assert.equal(brief.location.name, location.name)
    assert.equal(brief.location.description, location.description)
    assert.equal(brief.seriesVisualStyle, series.visualStyle)
    assert.ok(!body.prompt.includes(series.characterVisualStyle))
    assert.ok(body.system_prompt.includes('Remove all occupants'))
    calls++
    return new Response(JSON.stringify({ text:JSON.stringify({
      environment:'An empty classic American diner with red stools, a long counter, round tables and an espresso machine shaped like an inference server.',
      renderingStyle:'Rough 2D paper cutout illustration, flat bright palette and simple flat textures.',
    }) }))
  }
  const draft = seriesReferencePrompt(series, target)
  assert.ok(!draft.includes('huge heads'))
  const prepared = await prepareSeriesLocationPrompt('location-prompts', series, location.id, draft)
  assert.ok(prepared.includes('Zero people or characters'))
  assert.ok(prepared.includes('red stools'))
  assert.ok(prepared.includes('round tables'))
  assert.ok(prepared.includes('2D paper cutout'))
  assert.ok(!/huge heads|short legs|waitress|developers|apron/i.test(prepared))
  assert.ok(prepared.length < 1450)
  assert.equal(await prepareSeriesLocationPrompt('location-prompts', series, location.id, prepared), prepared)
  assert.equal(calls, 1)
  // Providers can exceed their schema's length hint; retain a bounded empty-set prompt.
  globalThis.fetch = async () => new Response(JSON.stringify({ text:JSON.stringify({
    environment:'An empty diner with red stools and round tables. '.repeat(40),
    renderingStyle:'Flat paper cutout with a bright palette. '.repeat(20),
  }) }))
  const bounded = await prepareSeriesLocationPrompt('long-location-prompt', series, location.id, draft)
  assert.ok(bounded.length < 1450)
  assert.ok(bounded.startsWith('Empty, unoccupied environment.'))
  assert.ok(bounded.includes('Environment rendering: Flat paper cutout'))
  assert.ok(bounded.endsWith('No text, labels or contact sheet.'))
  // A failed rewrite must never submit the generic series prompt to an image model.
  globalThis.fetch = async input => {
    assert.equal(String(input), '/api/v1/llm/generate')
    return new Response(JSON.stringify({ text:'{}' }))
  }
  await assert.rejects(generateSeriesReferenceImage('bad-location-prompt', series, target,
    { prompt:draft, beforeImport:async () => {} }), /valid empty-location prompt/)
})

test('late reference imports preserve edits and never change the active series', async () => {
  const { mergeSeriesReferenceImport } = await import('../src/features/series/referenceImages')
  const { useSeriesStore } = await import('../src/features/series/store')
  const source = project(), other = { ...project(), id:'other', title:'Other series' }
  const asset = { id:'new-image', kind:'character' as const, uri:'assets/new.png', workspaceId:'source', ownerType:'character' as const,
    ownerId:source.characters[0].id, isDerivedThumbnail:false, metadata:{} }
  const result = { asset, series:{ ...source, revision:source.revision + 1, assets:{ ...source.assets, [asset.id]:asset } } }
  const edited = { ...source, title:'New unsaved title' }
  const merged = mergeSeriesReferenceImport(edited, result)
  assert.equal(merged.title, edited.title)
  assert.ok(merged.characters[0].referenceAssetIds.includes(asset.id))
  useSeriesStore.setState({ workspace:'source', activeSeriesId:other.id, dirty:false,
    library:{ schema:'series-library', version:1, workspaceId:'source', seriesOrder:[source.id,other.id], seriesById:{ [source.id]:source, [other.id]:other } } })
  useSeriesStore.getState().acceptAssetImport('source', result)
  assert.equal(useSeriesStore.getState().activeSeriesId, other.id)
  assert.equal(useSeriesStore.getState().library.seriesById[other.id].title, 'Other series')
  assert.ok(useSeriesStore.getState().library.seriesById[source.id].assets[asset.id])
})

test('animation handoffs use the episode references and remain editable without rendering or invented 3D models', async () => {
  const { buildSeriesShotScene } = await import('../src/features/series/shotScene')
  const { parseSceneFile } = await import('../src/lib/sceneFile')
  const { parseScene3DDocument } = await import('../src/features/scene3d/document')
  const series = project(), episode = Object.values(series.episodesById)[0], shot = episode.shots[0]
  series.allowedProductionMethods = ['animation_2d','animation_3d']
  episode.canonSnapshot.characters = series.characters
  episode.canonSnapshot.locations = series.locations
  episode.canonSnapshot.assets = series.assets
  // A supplied image is visual evidence for an editable layer/plane, never a generated mesh.
  for (const entity of [...series.characters, ...series.locations]) {
    const id = `reference-${entity.id}`
    entity.referenceAssetIds = [id]
    if ('primaryReferenceAssetId' in entity) entity.primaryReferenceAssetId = id
    series.assets[id] = { id, kind:'image', uri:`assets/${id}.png`, ownerType:'series', ownerId:series.id, workspaceId:'source', isDerivedThumbnail:false, metadata:{} }
    entity.approval = 'approved'
  }
  episode.canonSnapshot.approvedReferenceAssetIds = Object.keys(series.assets)
  shot.productionMethod = 'animation_2d'
  const flat = buildSeriesShotScene('source', series, episode, shot)
  assert.equal(flat.dimension, '2d')
  assert.equal(parseSceneFile(JSON.stringify(flat.document)).duration, shot.durationSeconds)
  assert.ok(flat.document.layers.some(layer => layer.id === shot.locationId && layer.fill))
  shot.productionMethod = 'animation_3d'
  const spatial = buildSeriesShotScene('source', series, episode, shot)
  const parsed = parseScene3DDocument(spatial.document)
  assert.ok(parsed)
  assert.ok(parsed.slots.every(slot => slot.media === 'image'))
  assert.ok(parsed.slots.some(slot => slot.id === shot.locationId && slot.slot === 'background'))
  series.allowedProductionMethods = ['generated_video']
  assert.throws(() => buildSeriesShotScene('source', series, episode, shot), /does not permit/)
})

function animationProject() {
  const series = project(), episode = Object.values(series.episodesById)[0], shot = episode.shots[0]
  series.allowedProductionMethods = ['animation_2d', 'animation_3d']
  shot.productionMethod = 'animation_2d'
  shot.locationVariantId = ''
  shot.wardrobeByCharacterId = {}
  for (const entity of [...series.characters, ...series.locations]) {
    const id = `reference-${entity.id}`
    entity.referenceAssetIds = [id]
    if ('primaryReferenceAssetId' in entity) entity.primaryReferenceAssetId = id
    entity.approval = 'approved'
    series.assets[id] = { id, kind:'image', uri:`assets/${id}.png`, ownerType:'series', ownerId:series.id,
      workspaceId:'source', isDerivedThumbnail:false, metadata:{} }
  }
  episode.canonSnapshot = structuredClone({ characters:series.characters, locations:series.locations,
    assets:series.assets, approvedReferenceAssetIds:Object.keys(series.assets) })
  return { series, episode, shot }
}

test('both animation editors require an approved environment and every visible character from the episode snapshot', async () => {
  const { buildSeriesShotScene } = await import('../src/features/series/shotScene')
  const { seriesShotReferences } = await import('../src/features/series/shotReferences')
  for (const method of ['animation_2d', 'animation_3d'] as const) {
    const { series, episode, shot } = animationProject()
    shot.productionMethod = method
    const locationId = shot.locationId
    shot.locationId = ''
    assert.equal(seriesShotReferences(series, episode, shot).ready, false)
    assert.throws(() => buildSeriesShotScene('source', series, episode, shot), /Location: not assigned/)
    shot.locationId = locationId
    const refs = seriesShotReferences(series, episode, shot)
    assert.equal(refs.ready, true)
    const background = refs.background!
    for (const invalid of [{kind:'video'}, {isDerivedThumbnail:true}, {uri:''}]) {
      Object.assign(background, invalid)
      assert.throws(() => buildSeriesShotScene('source', series, episode, shot), /Location:/)
      Object.assign(background, series.assets[background.id])
    }
    refs.location!.approval = 'draft'
    assert.throws(() => buildSeriesShotScene('source', series, episode, shot), /Location:/)
    refs.location!.approval = 'approved'
    // New live references cannot silently change the frozen episode.
    const frozenAssets = episode.canonSnapshot.assets as typeof series.assets
    delete frozenAssets[refs.people[0].asset!.id]
    assert.ok(series.assets[refs.people[0].asset!.id])
    assert.throws(() => buildSeriesShotScene('source', series, episode, shot), /Character:/)
    shot.visibleCharacterIds = []
    assert.equal(seriesShotReferences(series, episode, shot).ready, true)
    const environmentOnly = buildSeriesShotScene('source', series, episode, shot)
    assert.equal(environmentOnly.dimension, method === 'animation_2d' ? '2d' : '3d')
  }
})

test('animation scene preparation uses the selected location variant image', async () => {
  const { seriesShotReferences } = await import('../src/features/series/shotReferences')
  const { series, episode, shot } = animationProject()
  const location = seriesShotReferences(series, episode, shot).location!
  const image = { ...series.assets[location.referenceAssetIds[0]], id:'night-image', uri:'assets/night.png' }
  ;(episode.canonSnapshot.assets as typeof series.assets)[image.id] = image
  ;(episode.canonSnapshot.approvedReferenceAssetIds as string[]).push(image.id)
  location.variants = [{ id:'night', label:'Night', description:'Night lighting', referenceAssetIds:[image.id] }]
  shot.locationVariantId = 'night'
  assert.equal(seriesShotReferences(series, episode, shot).background?.id, image.id)
})

test('shot controls show the missing environment before preparation and link to both reference rooms', async t => {
  const { render, fireEvent, cleanup } = await import('@testing-library/react')
  const { SeriesShotProduction } = await import('../src/features/series/SeriesShotProduction')
  const { ensureUiI18n } = await import('../src/i18n')
  const translate = ensureUiI18n().getFixedT('en', 'seriesLab')
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ outputs:[], total:0 }))
  t.after(() => { globalThis.fetch = originalFetch; cleanup() })
  const { series, episode, shot } = animationProject()
  const locationId = shot.locationId
  shot.locationId = ''
  let opened = '', updatedEpisode = false
  function Form() {
    const [current, setCurrent] = useState(shot)
    return <SeriesShotProduction workspace="source" series={series} episode={episode} shot={current}
      onChange={setCurrent} saveNow={async () => series} onOpenReferences={room => { opened = room }} onOpenEpisode={() => { updatedEpisode = true }} />
  }
  const view = render(<Form />)
  const prepare = view.getByRole('button', { name:translate('production.open2d') }) as HTMLButtonElement
  assert.equal(prepare.disabled, true)
  assert.ok(view.getByRole('status').textContent?.includes(translate('production.assets.completeFirst')))
  fireEvent.click(view.getByRole('button', { name:translate('production.assets.prepareLocations') }))
  assert.equal(opened, 'locations')
  fireEvent.click(view.getByRole('button', { name:translate('production.assets.prepareCharacters') }))
  assert.equal(opened, 'characters')
  fireEvent.click(view.getByRole('button', { name:translate('production.assets.updateEpisode') }))
  assert.equal(updatedEpisode, true)
  fireEvent.change(view.getByRole('combobox', { name:translate('production.assets.location') }), { target:{value:locationId} })
  assert.equal(prepare.disabled, false)
  assert.ok(view.getAllByRole('img').length >= 2)
})
