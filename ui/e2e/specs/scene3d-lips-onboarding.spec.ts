import { expect, test } from '@playwright/test'
import { speechApp, openSpeech, saveSpeech, seekSpeech } from '../helpers/speechFlow'
import { speechFixture, speechTestGlb } from '../helpers/speechAssets'
import { closeApp } from '../helpers/gotoApp'

test('place lips on the selected surface, retry a miss and cancel without changing placement', async ({ page }, info) => {
  test.setTimeout(90_000)
  const app = await speechApp(page), doc = speechFixture()
  doc.slots[0].speech = undefined
  doc.camera.framing = { targetSlot: 'subject_1', anchor: 'head', from: [0, 0, 1.5], to: [0, 0, 1.5] }
  await openSpeech(page, doc)
  await page.getByTestId('world3d-speech-toggle').click()
  await page.getByRole('button', { name: 'Place with a click on the face', exact: true }).click()
  const target = page.getByTestId('speech-pick-surface'), rect = (await target.boundingBox())!
  await target.click({ position: { x: 4, y: rect.height - 4 } })
  await expect(page.getByRole('status').filter({ hasText: 'Click the selected model' })).toBeVisible()
  await target.click({ position: { x: rect.width / 2, y: rect.height / 2 } })
  await expect(target).toHaveCount(0)
  const saved = await saveSpeech(page, info, 'clicked-mouth')
  expect(saved.slots[0].speech?.face?.meshIndex).toBe(0)
  expect(saved.slots[0].speech?.face?.center[1]).toBeGreaterThan(1.25)
  expect(saved.slots[0].speech?.eyes).toBe(false)
  await page.getByRole('button', { name: 'Place with a click on the face', exact: true }).click()
  await target.press('Escape')
  await expect(target).toHaveCount(0)
  const after = await saveSpeech(page, info, 'cancelled-placement')
  expect(after.slots[0].speech).toEqual(saved.slots[0].speech)
  await closeApp(page, app.session)
})

test('add lips without a recognized rig, apply bundled example, record and keep subjects independent', async ({ page }, info) => {
  test.setTimeout(90000)
  const app = await speechApp(page)
  await page.route('**/api/v1/file/speech-test.glb*', route => route.fulfill({ contentType: 'model/gltf-binary', body: speechTestGlb('UnrecognizedMesh') }))
  const doc = speechFixture(true)
  for (const slot of doc.slots) slot.speech = undefined
  await openSpeech(page, doc)
  await page.getByTestId('world3d-speech-toggle').click()
  const controls = page.getByTestId('scene3d-speech')
  await expect(controls.getByLabel('Placement profile')).toBeHidden()
  await controls.getByRole('button', { name: 'Add lips', exact: true }).click()
  await expect(controls).toContainText('No head landmark found')
  await controls.getByLabel('Mouth Y', { exact: true }).fill('1.36')
  await controls.getByLabel('Width', { exact: true }).fill('0.2')
  await controls.getByLabel('Height', { exact: true }).fill('0.13')
  await controls.getByRole('button', { name: 'Use English example', exact: true }).click()
  await expect(controls).toContainText('25 cues')
  await expect(controls.getByRole('button', { name: 'Use English example', exact: true })).toBeEnabled()
  await seekSpeech(page, 1.8)
  await expect(page.locator('[data-testid=speech-state][data-speaker=subject_1]')).toHaveAttribute('data-viseme', 'M')
  const saved = await saveSpeech(page, info, 'example')
  expect(saved.slots[0].speech?.face?.center[1]).toBe(1.36)
  expect(saved.slots[0].speech?.driver).toBe('rhubarb')
  expect(saved.slots[1].speech).toBeUndefined()
  await controls.getByLabel('Listen to this subject’s voice').evaluate(async element => {
    const audio = element as HTMLAudioElement
    Object.assign(window, { __previousVoicePreview: audio }); await audio.play()
  })
  await page.getByLabel('Character', { exact: true }).selectOption('subject_2')
  await expect.poll(() => page.evaluate(() => (window as unknown as { __previousVoicePreview: HTMLAudioElement }).__previousVoicePreview.paused)).toBe(true)
  await expect(controls.getByRole('button', { name: 'Add lips', exact: true })).toBeVisible()
  await page.getByLabel('Character', { exact: true }).selectOption('subject_1')
  // Simulated microphone signal; real MediaRecorder, decode, WAV conversion and upload.
  await page.evaluate(() => {
    navigator.mediaDevices.getUserMedia = async () => {
      const context = new AudioContext(), oscillator = context.createOscillator(), destination = context.createMediaStreamDestination()
      oscillator.connect(destination); oscillator.start()
      destination.stream.getTracks().forEach(track => {
        const stop = track.stop.bind(track)
        track.stop = () => { stop(); oscillator.stop(); void context.close() }
      })
      Object.assign(window, { __testMic: destination.stream })
      return destination.stream
    }
  })
  await controls.getByRole('button', { name: 'Record with microphone', exact: true }).click()
  await expect(controls).toContainText('Recording…')
  await page.waitForTimeout(1100)
  await controls.getByRole('button', { name: 'Stop recording', exact: true }).click()
  await expect(controls.getByLabel('Listen to recording')).toBeVisible()
  await expect.poll(() => page.evaluate(() => (window as unknown as { __testMic: MediaStream }).__testMic.getTracks()[0].readyState)).toBe('ended')
  await controls.getByRole('button', { name: 'Use recording for this subject', exact: true }).click()
  await expect(controls).toContainText('Volume-driven motion')
  const recorded = await saveSpeech(page, info, 'recorded')
  expect(recorded.slots[0].speech?.driver).toBe('amplitude')
  expect(recorded.slots[1].speech).toBeUndefined()
  await controls.getByRole('button', { name: 'Record with microphone', exact: true }).click()
  await expect(controls).toContainText('Recording…')
  await page.getByLabel('Character', { exact: true }).selectOption('subject_2')
  await expect.poll(() => page.evaluate(() => (window as unknown as { __testMic: MediaStream }).__testMic.getTracks()[0].readyState)).toBe('ended')
  await expect(controls.getByLabel('Listen to recording')).toHaveCount(0)
  await info.attach('lips-onboarding.png', { body: await page.screenshot(), contentType: 'image/png' })
  expect(app.requests).toHaveLength(0)
  await closeApp(page, app.session)
})

test('reopened isolated voice keeps isolation until explicitly disabled', async ({ page }, info) => {
  const app = await speechApp(page), doc = speechFixture(false, true)
  doc.slots[0].speech!.clips![0].driver = 'rhubarb-vocals'
  await page.route('**/api/v1/character-kits/speech/capabilities', route => route.fulfill({ json: { rhubarb: true, vocalIsolation: { available: true } } }))
  const requests: boolean[] = []
  await page.route('**/api/v1/character-kits/speech/analyze*', route => {
    requests.push(new URL(route.request().url()).searchParams.get('isolate_vocals') === 'true')
    return route.fulfill({ json: { mouthCues: [{ start: 0, end: 1, value: 'D' }], duration: 1 } })
  })
  await openSpeech(page, doc)
  const option = page.getByLabel('Isolate vocals before calculating lips', { exact: true })
  await expect(option).toBeChecked()
  await page.getByRole('button', { name: 'Calculate gestures with Rhubarb (local)', exact: true }).click()
  await expect.poll(() => requests).toEqual([true])
  await expect(page.getByTestId('scene3d-speech')).toContainText('1 cue')
  const saved = await saveSpeech(page, info, 'isolated-reanalysis')
  expect(saved.slots[0].speech?.clips?.[0].driver).toBe('rhubarb-vocals')
  await option.uncheck()
  await page.getByRole('button', { name: 'Calculate gestures with Rhubarb (local)', exact: true }).click()
  await expect.poll(() => requests).toEqual([true, false])
  await expect(page.getByTestId('scene3d-speech')).toContainText('1 cue')
  expect((await saveSpeech(page, info, 'explicit-mixed-reanalysis')).slots[0].speech?.clips?.[0].driver).toBe('rhubarb')
  await closeApp(page, app.session)
})
