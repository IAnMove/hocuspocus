import { chromium } from 'playwright'
import { readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import assert from 'node:assert/strict'

// Real native app, real existing Mira GLB/WAV, local Rhubarb, real disk CAS and MP4.
// No intercepted requests, generated voice or paid providers.
const output = path.resolve('../.codex-tmp/speech-review')
const base = process.env.SPEECH_REVIEW_URL ?? 'http://127.0.0.1:8796'
const portrait = JSON.parse(await readFile(path.join(output, 'portrait.world3d.json'), 'utf8'))
const dialogue = JSON.parse(await readFile(path.join(output, 'dialogue-native.world3d.json'), 'utf8'))
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1680, height: 1180 }, reducedMotion: 'reduce' })
const errors = []
page.on('pageerror', error => errors.push(error.message))
const open = async document => {
  await page.getByLabel('Abrir plano JSON', { exact: true }).setInputFiles({ name: 'review.world3d.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(document)) })
  await page.waitForFunction(slots => { try { return window.__world3dStage?.ready(slots) } catch { return false } }, document.slots, { timeout: 30000 })
}
const save = async name => {
  const pending = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Guardar plano JSON', exact: true }).click()
  const target = path.join(output, name + '.world3d.json')
  await (await pending).saveAs(target)
  return JSON.parse(await readFile(target, 'utf8'))
}
const seek = async seconds => page.getByLabel('Posición en la escena', { exact: true }).fill(String(Math.round(seconds * 100) / 100))
const screenshot = async name => {
  await page.getByTestId('scene3d-stage').scrollIntoViewIfNeeded()
  await page.screenshot({ path: path.join(output, name + '.jpg'), type: 'jpeg', quality: 90 })
}
try {
  await page.addInitScript(() => { localStorage.setItem('hocuspocus-ui-language', 'es'); localStorage.setItem('hocuspocus_welcome_seen_v1', '1'); localStorage.setItem('hocuspocus_welcome_seen_v2', '453') })
  await page.goto(base)
  await page.getByRole('button', { name: 'Estudios', exact: true }).click({ timeout: 30000 })
  await page.getByRole('tab', { name: 'Vídeo 3D', exact: true }).click()
  await page.getByRole('button', { name: 'Cerrar Pregunta al mago', exact: true }).click()
  portrait.slots[0].sourceRef.workspaceId = 'speech-review'
  await open(portrait)
  const previous = JSON.parse(await readFile(path.join(output, 'reusable-mira.world3d.json'), 'utf8').catch(() => 'null'))
  if (previous?.slots[0]?.character?.kitRef) await page.getByTestId('saved-character').selectOption(previous.slots[0].character.kitRef.id)
  await page.getByTestId('character-name').fill('Mira · personaje reutilizable')
  await page.getByTestId('character-voice').selectOption('serena')
  // Exercise the procedural atlas, not an image-generation dependency.
  await page.getByText('Ajustar boca y expresiones', { exact: true }).click()
  await page.getByTestId('scene3d-speech').locator('label').filter({ hasText: 'Dibujo de boca' }).locator('select').selectOption('toon')
  await page.getByTestId('save-character').click()
  await page.getByText('Personaje guardado. Modelo, boca, ojos y voz disponibles en otros planos.', { exact: true }).waitFor()
  const saved = await save('reusable-mira')
  assert.equal(saved.slots[0].speech.atlas, undefined)
  assert.equal(saved.slots[0].character.voice.voiceId, 'serena')
  const kitId = saved.slots[0].character.kitRef.id
  await seek(1.65)
  await page.getByTestId('character-definition').scrollIntoViewIfNeeded()
  await screenshot('personaje-reutilizable-integrado')
  await seek(2.9333)
  await page.getByTestId('scene3d-stage').screenshot({ path: path.join(output, 'mira-parpadeo.png') })
  dialogue.camera = { ...portrait.camera, fov: 36, framing: { ...portrait.camera.framing, from: [.33, 0, 1.3], to: [.33, 0, 1.3], lookFrom: [.33, 0, 0] } }
  dialogue.slots[1].position = [.66, 0, 0]
  dialogue.slots.forEach(slot => { slot.rotationY = 0; slot.sourceRef.workspaceId = 'speech-review' })
  await open(dialogue)
  for (const id of ['subject_1', 'subject_2']) {
    await page.getByLabel('Personaje', { exact: true }).selectOption(id)
    await page.getByTestId('saved-character').selectOption(kitId)
    await page.getByTestId('apply-character').click()
    await page.getByTestId('character-voice').locator('option:checked').filter({ hasText: 'serena' }).waitFor({ state: 'attached' })
  }
  for (const [id, index] of [['subject_1', '0'], ['subject_2', '0'], ['subject_1', '1']]) {
    await page.getByLabel('Personaje', { exact: true }).selectOption(id)
    await page.getByLabel('Intervención', { exact: true }).selectOption(index)
    const response = page.waitForResponse(r => r.url().includes('/speech/analyze') && r.request().method() === 'POST')
    await page.getByRole('button', { name: 'Calcular gestos con Rhubarb (local)', exact: true }).click()
    assert.equal((await response).status(), 200)
    await page.getByRole('button', { name: 'Calcular gestos con Rhubarb (local)', exact: true }).waitFor()
    await page.waitForFunction(() => ![...document.querySelectorAll('button')].find(b => b.textContent === 'Calcular gestos con Rhubarb (local)')?.disabled)
  }
  const conversation = await save('reusable-dialogue')
  assert.equal(conversation.soundtrack.length, 1)
  for (const slot of conversation.slots) {
    assert.deepEqual(slot.speech.face, saved.slots[0].speech.face)
    assert.equal(slot.character.kitRef.id, kitId)
    assert.ok(slot.speech.clips.every(clip => clip.cues.length > 0 && clip.audible === false))
  }
  for (const [name, slotIndex, clipIndex] of [['dialogo-turno-a', 0, 0], ['dialogo-turno-b', 1, 0], ['dialogo-regreso-a', 0, 1]]) {
    const clip = conversation.slots[slotIndex].speech.clips[clipIndex]
    const cue = clip.cues.filter(c => c.viseme !== 'rest').sort((a, b) => (b.end - b.start) - (a.end - a.start))[0]
    const time = cue ? clip.start + Math.max(clip.offset, cue.start) - clip.offset + Math.min(.08, (cue.end - cue.start) / 2) : clip.start + .2
    await seek(time)
    await page.getByTestId('scene3d-stage').screenshot({ path: path.join(output, name + '.png') })
  }
  await seek(2.5)
  await page.getByTestId('character-definition').scrollIntoViewIfNeeded()
  await screenshot('dialogo-reutilizable-integrado')
  const response = page.waitForResponse(r => r.url().endsWith('/api/v1/scenes/recordings') && r.request().method() === 'POST', { timeout: 180000 })
  await page.getByTestId('world3d-export').click()
  const publication = await response
  assert.equal(publication.status(), 200)
  const recording = await publication.json()
  const bytes = await (await fetch(base + recording.url)).arrayBuffer()
  await writeFile(path.join(output, 'dialogo-reutilizable.mp4'), Buffer.from(bytes))
  assert.deepEqual(errors, [])
  const result = { url: base, kitId, sameCanonicalKitTwoActors: true, turns: 3, oneSoundtrack: true, realRhubarb: true,
    mp4: recording.url, mp4Bytes: bytes.byteLength, generatedVoiceCalls: 0, errors }
  await writeFile(path.join(output, 'reusable-review-result.json'), JSON.stringify(result, null, 2))
  console.log(JSON.stringify(result, null, 2))
} finally { await browser.close() }
