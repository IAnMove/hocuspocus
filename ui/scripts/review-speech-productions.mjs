import { chromium } from 'playwright'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import path from 'node:path'
import assert from 'node:assert/strict'

// Real Hocuspocus shell, local GLB/audio, local Rhubarb and native MP4 export.
// Requires the isolated review API, never the generation runtime.
const base = process.env.SPEECH_REVIEW_URL ?? 'http://127.0.0.1:8796'
const output = path.resolve('../.codex-tmp/speech-review')
await mkdir(output, { recursive: true })
const portraitPath = path.join(output, 'portrait.world3d.json')
const portrait = JSON.parse(await readFile(portraitPath, 'utf8'))
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1680, height: 1180 }, reducedMotion: 'reduce' })
const errors = [], failedRequests = []
page.on('pageerror', error => errors.push(error.message))
page.on('response', response => { if (response.status() >= 400 && response.status() !== 404) failedRequests.push(response.status() + ' ' + response.url()) })
const saveShot = async name => {
  const downloading = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Guardar plano JSON', exact: true }).click()
  const file = path.join(output, name + '.world3d.json')
  await (await downloading).saveAs(file)
  return JSON.parse(await readFile(file, 'utf8'))
}
const prepare = async (kind, cast, lines) => page.evaluate(async ({ portrait, kind, cast, lines }) => {
  const { prepareSpeechProduction, openSpeechProduction } = await import('/src/features/scene3d/speech/prepareProduction.ts')
  const original = portrait.slots[0]
  const doc = await prepareSpeechProduction({ kind, title: kind === 'song' ? 'Mira · voz sobre canción / recorte de prueba' : 'Mira · tres turnos de diálogo',
    sourceId: 'local-review/' + kind, workspace: 'speech-review', duration: 6, offset: 1,
    cast, audio: original.speech.audio, lines })
  if (kind === 'song') {
    doc.camera = portrait.camera
    doc.slots[0].position = original.position
    doc.slots[0].scale = original.scale
    doc.slots[0].rotationY = original.rotationY
  }
  openSpeechProduction(doc)
  return doc
}, { portrait, kind, cast, lines })
try {
  await page.addInitScript(() => {
    localStorage.setItem('hocuspocus-ui-language', 'es')
    localStorage.setItem('hocuspocus_welcome_seen_v1', '1')
    localStorage.setItem('hocuspocus_welcome_seen_v2', '453')
  })
  await page.goto(base)
  await page.getByRole('button', { name: 'Estudios', exact: true }).click({ timeout: 30000 })
  await page.getByRole('tab', { name: 'Vídeo 3D', exact: true }).click()
  await page.getByRole('button', { name: 'Cerrar Pregunta al mago', exact: true }).click()
  await page.getByLabel('Abrir plano JSON', { exact: true }).setInputFiles(portraitPath)
  await page.waitForFunction(slots => window.__world3dStage?.ready(slots), portrait.slots, { timeout: 30000 })
  await page.getByRole('button', { name: 'Recuperar ajuste guardado', exact: true }).click()
  await page.getByRole('button', { name: 'Guardar ajuste para este modelo', exact: true }).click()
  await page.getByText('Ajuste guardado para este GLB. Se reutilizará en otros planos del workspace.', { exact: true }).waitFor()
  const model = { workspaceId: 'speech-review', filename: portrait.slots[0].sourceUrl.split('/').at(-1), url: portrait.slots[0].sourceUrl }
  const song = await prepare('song', [{ id: 'mira', name: 'Mira', model }])
  await page.getByTestId('speech-production-origin').getByText('Mira · voz sobre canción / recorte de prueba', { exact: false }).waitFor()
  await page.waitForFunction(slots => window.__world3dStage?.ready(slots.map(s => ({ ...s, speech: undefined }))), song.slots)
  // Wait for automatic profile load to commit (save through the actual UI).
  await page.getByRole('button', { name: 'Guardar ajuste para este modelo', exact: true }).waitFor()
  await page.waitForFunction(() => ![...document.querySelectorAll('button')].find(b => b.textContent === 'Guardar ajuste para este modelo')?.disabled)
  const savedSong = await saveShot('song-native')
  assert.deepEqual(savedSong.slots[0].speech.face, portrait.slots[0].speech.face)
  assert.ok(savedSong.slots[0].speech.clips[0].cues.length > 8)
  assert.equal(savedSong.soundtrack.length, 1)
  assert.equal(savedSong.slots[0].speech.clips[0].audible, false)
  const audioProof = await page.evaluate(async doc => {
    const { mixSceneSpeech, decodeVoice } = await import('/src/features/scene3d/speech/audio.ts')
    const mixed = await mixSceneSpeech(doc), original = await decodeVoice(doc.soundtrack[0].audio.url)
    const samples = mixed.getChannelData(0), source = original.getChannelData(0)
    let maxDelta = 0
    for (let i = 200; i < samples.length - 200; i += 127) maxDelta = Math.max(maxDelta, Math.abs(samples[i] - source[i + 48000]))
    return { duration: mixed.duration, channels: mixed.numberOfChannels, maxDelta }
  }, savedSong)
  assert.equal(audioProof.duration, 6)
  assert.ok(audioProof.maxDelta < .001, 'Soundtrack must equal the original fragment, not doubled audio')
  await page.getByRole('button', { name: 'Reproducir', exact: true }).click()
  await page.waitForFunction(() => Number(document.querySelector('[aria-label="Posición en la escena"]')?.value) > 1.2)
  await page.getByRole('button', { name: 'Pausar', exact: true }).click()
  await page.getByRole('heading', { name: 'Estudio de escenas 3D', exact: true }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: path.join(output, 'productions-integrado.jpg'), type: 'jpeg', quality: 88 })
  const recording = page.waitForResponse(r => r.url().endsWith('/api/v1/scenes/recordings') && r.request().method() === 'POST', { timeout: 180000 })
  await page.getByTestId('world3d-export').click()
  const response = await recording
  assert.equal(response.status(), 200)
  const recorded = await response.json()
  const video = await page.request.get(base + recorded.url)
  await writeFile(path.join(output, 'song-native.mp4'), await video.body())
  await page.getByTestId('world3d-export').waitFor({ state: 'visible' })
  const secondModel = { ...model, filename: '44922245266e4e648c38dbd3671ab674.glb', url: '/api/review/files/44922245266e4e648c38dbd3671ab674.glb' }
  const dialogue = await prepare('episode', [{ id: 'mira', name: 'Mira', model }, { id: 'mira-b', name: 'Mira (segunda toma)', model: secondModel }],
    [{ id: 'one', characterId: 'mira', text: 'Primera intervención', start: 0, end: 1.8 },
      { id: 'two', characterId: 'mira-b', text: 'Respuesta', start: 2, end: 3.8 },
      { id: 'three', characterId: 'mira', text: 'Última intervención', start: 4, end: 6 }])
  await page.waitForFunction(slots => window.__world3dStage?.ready(slots.map(s => ({ ...s, speech: undefined }))), dialogue.slots)
  await page.getByLabel('Personaje', { exact: true }).selectOption('subject_2')
  await page.waitForFunction(() => ![...document.querySelectorAll('button')].find(b => b.textContent === 'Guardar ajuste para este modelo')?.disabled)
  const savedDialogue = await saveShot('dialogue-native')
  assert.deepEqual(savedDialogue.slots[1].speech.face, portrait.slots[0].speech.face)
  assert.equal(savedDialogue.slots[0].speech.clips.length, 2)
  await page.getByLabel('Personaje', { exact: true }).selectOption('subject_1')
  await page.getByLabel('Intervención', { exact: true }).selectOption('1')
  await page.getByRole('heading', { name: 'Estudio de escenas 3D', exact: true }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: path.join(output, 'dialogue-integrado.jpg'), type: 'jpeg', quality: 88 })
  assert.deepEqual(errors, [])
  assert.deepEqual(failedRequests, [])
  const result = { url: base, audioProof, exported: recorded, songCues: savedSong.slots[0].speech.clips[0].cues.length,
    dialogueTurns: savedDialogue.slots.map(s => s.speech?.clips?.length), reusedAcrossUploadUrls: true, errors, failedRequests }
  await writeFile(path.join(output, 'productions-result.json'), JSON.stringify(result, null, 2))
  console.log(JSON.stringify(result, null, 2))
} catch (error) {
  console.log((await page.locator('body').innerText()).slice(-7000))
  console.log({ errors, failedRequests })
  await page.screenshot({ path: path.join(output, 'productions-failure.jpg'), type: 'jpeg' })
  throw error
} finally { await browser.close() }
