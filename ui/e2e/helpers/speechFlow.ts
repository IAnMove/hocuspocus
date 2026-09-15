import { expect, type Page, type TestInfo } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { gotoApp } from './gotoApp'
import { speechTestGlb, speechTestWav } from './speechAssets'
import type { Scene3DDocument } from '../../src/features/scene3d/types'
import { emptyCharacterKitLibrary, type CharacterKitLibrary } from '../../src/lib/characterKit'
import { finalizeSpeechRecording } from './finalizeSpeechRecording'

export async function speechApp(page: Page) {
  // Observe real audio elements without changing their playback behavior.
  await page.addInitScript(() => {
    const OriginalAudio = window.Audio
    const observed: HTMLAudioElement[] = []
    Object.assign(window, { __speechPlayers: observed })
    window.Audio = function(source?: string) { const audio = new OriginalAudio(source); observed.push(audio); return audio } as typeof Audio
  })
  const session = await gotoApp(page), requests: Record<string, unknown>[] = []
  let library: CharacterKitLibrary = emptyCharacterKitLibrary()
  const wav = speechTestWav(), glb = speechTestGlb()
  await page.route('**/api/v1/character-kits/library**', async route => {
    if (route.request().method() === 'PATCH') {
      const body = route.request().postDataJSON()
      if (body.baseRevision !== library.revision) return route.fulfill({ status: 409, json: { detail: 'Library revision conflict' } })
      library = { ...library, revision: library.revision + 1, activeId: body.kit.id, kits: { ...library.kits, [body.kit.id]: body.kit } }
    }
    await route.fulfill({ json: library })
  })
  await page.route('**/api/v1/character-kits/speech/digest*', route => route.fulfill({ json: { digest: '0'.repeat(64), bytes: 12 } }))
  await page.route('**/api/v1/character-kits/speech/profiles/**', route => route.fulfill({ status: 404, json: {} }))
  await page.route('**/api/v1/file/speech-test.glb*', route => route.fulfill({ contentType: 'model/gltf-binary', body: glb }))
  await page.route('**/api/v1/file/speech-test.wav*', route => route.fulfill({ contentType: 'audio/wav', body: wav }))
  await page.route('**/api/v1/file/tts-test.wav*', route => route.fulfill({ contentType: 'audio/wav', body: speechTestWav(1) }))
  await page.route('**/api/v1/upload', route => route.fulfill({ json: { filename: 'speech-test.wav', url: '/api/v1/file/speech-test.wav?workspace=default', path: 'speech-test.wav' } }))
  await page.route('**/api/v1/upload-audio', route => route.fulfill({ json: { filename: 'speech-test.wav', url: '/api/v1/file/speech-test.wav?workspace=default', path: 'speech-test.wav' } }))
  await page.route('**/api/v1/character-kits/speech/analyze', route => {
    // Simulated phonetic recognizer, real WAV from browser resampling/trimming.
    const data = route.request().postDataBuffer()!, samples = (data.length - 44) / 2, rate = data.readUInt32LE(24)
    const cues: { start: number; end: number; value: string }[] = []
    for (let i = 0; i < samples; i += 320) {
      let peak = 0
      for (let j = i; j < Math.min(i + 320, samples); j++) peak = Math.max(peak, Math.abs(data.readInt16LE(44 + j * 2)))
      const value = peak > 100 ? 'D' : 'X', end = Math.min(samples, i + 320) / rate
      if (cues.at(-1)?.value === value) cues[cues.length - 1].end = end
      else cues.push({ start: i / rate, end, value })
    }
    return route.fulfill({ json: { mouthCues: cues, duration: samples / rate, recognizer: 'phonetic' } })
  })
  await page.route('**/api/v1/generate', route => {
    requests.push(route.request().postDataJSON())
    return route.fulfill({ json: { job_id: 'speech-test-job', status: 'queued' } })
  })
  await page.route('**/api/v1/status/speech-test-job', route => route.fulfill({ json: { status: 'completed', output_files: ['tts-test.wav'] } }))
  let exported: Buffer | undefined
  await page.route('**/api/v1/scenes/recordings', async route => {
    exported = await finalizeSpeechRecording(route.request())
    await route.fulfill({ json: { name: 'speech-export.mp4', url: '/api/v1/file/speech-export.mp4', type: 'video', size: exported.length, created_at: 0 } })
  })
  await page.route('**/api/v1/file/speech-export.mp4*', route => route.fulfill({ contentType: 'video/mp4', body: exported! }))
  await page.getByRole('tab', { name: 'Video 3D', exact: true }).click()
  await page.getByRole('button', { name: 'Close Ask to the Wizard' }).click()
  await page.getByRole('button', { name: 'Expand editor', exact: true }).click()
  return { session, requests, library: () => library }
}
export async function openSpeech(page: Page, doc: Scene3DDocument) {
  await page.getByLabel('Open shot JSON', { exact: true }).setInputFiles({ name: 'speech.world3d.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(doc)) })
  await expect(page.getByTestId('scene3d-roundtrip')).toHaveText('ok')
  await page.waitForFunction(slots => {
    const stage = (window as Window & { __world3dStage?: { ready: (slots: unknown[]) => boolean } }).__world3dStage
    try { return stage?.ready(slots) } catch { return false }
  }, doc.slots, { timeout: 20000 })
}
export async function saveSpeech(page: Page, info: TestInfo, name: string): Promise<Scene3DDocument> {
  const promise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Save shot JSON', exact: true }).click()
  const path = info.outputPath(name + '.world3d.json'); await (await promise).saveAs(path)
  return JSON.parse(await readFile(path, 'utf8'))
}
export async function seekSpeech(page: Page, seconds: number) {
  await page.getByLabel('Scene position', { exact: true }).fill(String(seconds))
}
export async function exportSpeech(page: Page, info: TestInfo) {
  const aac = await page.evaluate(async () => typeof AudioEncoder !== 'undefined' && (await AudioEncoder.isConfigSupported({
    codec: 'mp4a.40.2', sampleRate: 48000, numberOfChannels: 1, bitrate: 128000,
  })).supported)
  // Keep Windows testing native AAC; Linux now validates server PCM finalization.
  if (process.env.HOCUSPOCUS_REQUIRE_SPEECH_AAC === '1' || process.platform === 'win32') expect(aac, 'The real-export runner must provide AAC encoding').toBe(true)
  const response = page.waitForResponse(r => r.url().endsWith('/scenes/recordings') && r.request().method() === 'POST', { timeout: 90000 })
  await page.getByTestId('world3d-export').click()
  expect((await response).ok()).toBeTruthy()
  await expect(page.getByTestId('world3d-export')).toBeEnabled()
  const proof = await page.evaluate(async () => {
    const blob = (window as Window & { __world3dLastMp4?: Blob }).__world3dLastMp4!
    const decoded = await new OfflineAudioContext(1, 1, 48000).decodeAudioData(await blob.arrayBuffer())
    const samples = decoded.getChannelData(0)
    let sum = 0
    for (const value of samples) sum += value * value
    return { bytes: Array.from(new Uint8Array(await blob.arrayBuffer())), duration: decoded.duration, rms: Math.sqrt(sum / samples.length) }
  })
  expect(proof.bytes.length).toBeGreaterThan(1000)
  expect(proof.rms).toBeGreaterThan(.05); expect(proof.rms).toBeLessThan(.13) // Original tone, not two copies.
  await info.attach('native-h264-aac.mp4', { body: Buffer.from(proof.bytes), contentType: 'video/mp4' })
  return { encoded: true as const, ...proof }
}
