import { expect, test, type APIRequestContext, type Page, type TestInfo } from '@playwright/test'
import { isolateLiveWorkspace, liveConfig } from '../helpers/liveWorkspace'
import { liveJson as json } from '../helpers/liveRead'
import fs from 'node:fs/promises'
import type { ComicProject } from '../../src/features/comics/types'
import type { SeriesLibrary } from '../../src/features/series/types'

const scenario = process.env.HOCUSPOCUS_E2E_SCENARIO || 'smoke'
const expectedMode = process.env.HOCUSPOCUS_E2E_PROFILE || 'simulate'


function wizardPanel(page: Page) {
  return page.locator(
    '[role="dialog"][aria-label="Ask to the Wizard"], [role="region"][aria-label="Ask to the Wizard"]',
  ).first()
}

async function openApp(page: Page) {
  page.setDefaultTimeout(20_000)
  await page.addInitScript(() => {
    window.localStorage.setItem('hocuspocus_welcome_seen_v1', '1')
    window.localStorage.setItem('hocuspocus_welcome_seen_v2', '453')
  })
  await page.goto('/')
  const skip = page.getByRole('button', { name: 'Skip' })
  await skip.click({ timeout: 8_000 }).catch(() => undefined)
  if (expectedMode === 'real') {
    await expect(page.getByTestId('execution-mode-banner')).toHaveCount(0)
  } else {
    await expect(page.getByTestId('execution-mode-banner')).toContainText(expectedMode)
  }
  const panel = wizardPanel(page)
  const opened = await panel.waitFor({ state: 'visible', timeout: 20_000 }).then(() => true).catch(() => false)
  if (!opened) {
    await page.getByRole('button', { name: 'Expand Ask to the Wizard' }).click()
  }
  await expect(panel).toBeVisible()
  await expect(panel.getByText('Saludos, creador. Soy el mago de HocusPocus', { exact: false })).toBeVisible()
}

async function ask(page: Page, prompt: string, options: { allowFailure?: boolean } = {}): Promise<string> {
  const panel = wizardPanel(page)
  const input = panel.getByPlaceholder('Ask HocusPocus for a spell…')
  await input.fill(prompt)
  const responsePending = page.waitForResponse(response => response.url().endsWith('/api/v1/llm/generate') && response.request().method() === 'POST', { timeout: 120_000 })
  await panel.getByRole('button', { name: 'Ask to the Wizard', exact: true }).click()
  const response = await responsePending
  expect(response.ok(), `Wizard LLM HTTP ${response.status()}: ${await response.text()}`).toBeTruthy()
  await expect(input).toBeEnabled({ timeout: 25 * 60_000 })
  const transcript = (await panel.textContent()) || ''
  expect(transcript).not.toContain('No he podido consultar el LLM')
  if (!options.allowFailure) expect(transcript).not.toContain('No se pudo')
  return transcript
}

async function rootTaskIds(request: APIRequestContext, workspace: string): Promise<Set<string>> {
  const payload = await json(request, `/api/v1/tasks?status=all&workspace=${encodeURIComponent(workspace)}`) as {
    tasks: Array<{ id: string; parent_id?: string | null }>
  }
  return new Set(payload.tasks.filter(item => !item.parent_id).map(item => item.id))
}

async function waitForStorySongVersion(request: APIRequestContext, workspace: string, title: string, minimumVersions: number) {
  await expect.poll(async () => {
    const library = await json(request, `/api/v1/stories/library?workspace=${encodeURIComponent(workspace)}`) as {
      projects: Record<string, { title: string; music?: { cues?: Array<{ candidates?: unknown[] }> } }>
    }
    const project = Object.values(library.projects).find(item => item.title === title)
    return Math.max(0, ...(project?.music?.cues || []).map(cue => cue.candidates?.length || 0))
  }, { timeout: 60_000, intervals: [250, 500, 1_000, 2_000] }).toBeGreaterThanOrEqual(minimumVersions)
}

async function storyProjectIds(request: APIRequestContext, workspace: string): Promise<Set<string>> {
  const library = await json(request, `/api/v1/stories/library?workspace=${encodeURIComponent(workspace)}`) as {
    projects: Record<string, { id?: string }>
  }
  return new Set(Object.entries(library.projects || {}).flatMap(([key, project]) => (
    project.id && project.id !== key ? [key, project.id] : [key]
  )))
}

async function waitForNewStoryProject(
  request: APIRequestContext,
  workspace: string,
  previous: Set<string>,
  expectedTitle?: string,
) {
  let projectId = ''
  await expect.poll(async () => {
    const library = await json(request, `/api/v1/stories/library?workspace=${encodeURIComponent(workspace)}`) as {
      projects: Record<string, { id?: string; title?: string }>
    }
    projectId = Object.entries(library.projects || {})
      .find(([id, project]) => (
        !previous.has(id)
        && !previous.has(String(project.id || ''))
        && (!expectedTitle || project.title === expectedTitle)
      ))?.[0] || ''
    return projectId
  }, { timeout: 60_000, intervals: [250, 500, 1_000, 2_000] }).not.toBe('')
  const library = await json(request, `/api/v1/stories/library?workspace=${encodeURIComponent(workspace)}`) as {
    projects: Record<string, Record<string, unknown>>
  }
  return { id: projectId, project: library.projects[projectId] }
}

async function directorPipelineIds(request: APIRequestContext): Promise<Set<string>> {
  const payload = await json(request, '/api/v1/director/pipelines?limit=100') as {
    pipelines: Array<{ id: string }>
  }
  return new Set(payload.pipelines.map(item => item.id))
}

async function waitForCompletedDirectorPipeline(request: APIRequestContext, previous: Set<string>) {
  await expect.poll(async () => {
    const payload = await json(request, '/api/v1/director/pipelines?limit=100') as {
      pipelines: Array<{ id: string; status: string; pipeline_type?: string }>
    }
    const pipeline = payload.pipelines.find(item => !previous.has(item.id) && item.pipeline_type === 'music_video')
    if (!pipeline) return 'missing'
    return pipeline.status
  }, { timeout: 20 * 60_000, intervals: [500, 1_000, 2_000, 5_000] }).toBe('completed')
}

async function waitForTerminalRoot(
  request: APIRequestContext,
  workspace: string,
  previous: Set<string>,
  expectedStatus: 'terminal' | 'completed' = 'terminal',
) {
  // Cold-loading ACE-Step can briefly block the API worker while the model is
  // moved into reserved RAM. Keep observing the same task rather than
  // turning that transient lack of an HTTP response into a duplicate run.
  const taskJson = (path: string) => json(request, path, { timeout: 180_000 })
  let taskId = ''
  await expect.poll(async () => {
    const payload = await taskJson(`/api/v1/tasks?status=all&workspace=${encodeURIComponent(workspace)}`) as {
      tasks: Array<{ id: string; parent_id?: string | null }>
    }
    taskId = payload.tasks.find(item => !item.parent_id && !previous.has(item.id))?.id || ''
    return taskId
  }, { timeout: 60_000, intervals: [250, 500, 1_000, 2_000] }).not.toBe('')
  let terminalStatus = ''
  await expect.poll(async () => {
    const payload = await taskJson(`/api/v1/tasks?status=all&workspace=${encodeURIComponent(workspace)}`) as {
      tasks: Array<{ id: string; parent_id?: string | null; status: string }>
    }
    terminalStatus = payload.tasks.find(item => item.id === taskId)?.status || ''
    return terminalStatus
  }, { timeout: 20 * 60_000, intervals: [500, 1_000, 2_000, 5_000] }).toMatch(/completed|failed|cancelled/)
  if (expectedStatus === 'completed') expect(terminalStatus).toBe('completed')
  return taskId
}

type WizardMediaTask = {
  id: string
  status: string
  kind: string
  model?: string
  result_refs?: string[]
  metadata?: Record<string, unknown>
  created_at?: number
  started_at?: number | null
  completed_at?: number | null
}

type WizardMediaOutput = {
  name: string
  type: string
  url: string
  size: number
}

/**
 * Resolve a real Wizard-submitted task through the canonical output registry.
 * This deliberately observes the task and downloads its published bytes; it
 * never submits a second request or calls a capability executor directly.
 */
async function waitForWizardMedia(
  page: Page,
  request: APIRequestContext,
  info: TestInfo,
  workspace: string,
  previous: Set<string>,
  label: string,
  kind: 'image' | 'audio',
) {
  const taskId = await waitForTerminalRoot(request, workspace, previous, 'completed')
  const taskPayload = await json(request, `/api/v1/tasks?status=all&workspace=${encodeURIComponent(workspace)}`) as {
    tasks: WizardMediaTask[]
  }
  const task = taskPayload.tasks.find(item => item.id === taskId)
  expect(task, `Canonical ${label} task must remain observable`).toBeTruthy()
  expect(task?.metadata?.actor).toBe('wizard')
  expect(task?.metadata?.capability).toBe('start_generation')
  expect(task?.result_refs?.length).toBeGreaterThan(0)

  const outputsPayload = await json(request, `/api/v1/outputs?workspace=${encodeURIComponent(workspace)}`) as {
    outputs: WizardMediaOutput[]
  }
  const output = outputsPayload.outputs.find(item => (
    item.type === kind && task?.result_refs?.includes(item.name)
  ))
  expect(output, `Canonical ${label} output must be published`).toBeTruthy()
  const mediaResponse = await request.get(output!.url)
  expect(mediaResponse.ok(), `${label} output must be downloadable`).toBeTruthy()
  const bytes = await mediaResponse.body()
  expect(bytes.length).toBeGreaterThan(256)
  const metadataResponse = await request.get(
    `/api/v1/outputs/${encodeURIComponent(output!.name)}/metadata?workspace=${encodeURIComponent(workspace)}`,
  )
  expect(metadataResponse.ok(), `${label} metadata must be readable`).toBeTruthy()
  const metadata = await metadataResponse.json() as Record<string, unknown>
  expect((metadata.origin as Record<string, unknown> | undefined)?.actor).toBe('wizard')
  expect((metadata.execution as Record<string, unknown> | undefined)?.status).toBe('completed')
  expect((metadata.execution as Record<string, unknown> | undefined)?.mode).toBe('real')

  const decoded = await page.evaluate(({ url, mediaKind }) => new Promise<Record<string, number>>((resolve, reject) => {
    if (mediaKind === 'image') {
      const image = new Image()
      image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight })
      image.onerror = () => reject(new Error('Browser could not decode Wizard image output'))
      image.src = url
      return
    }
    const audio = new Audio()
    audio.onloadedmetadata = () => resolve({ duration: audio.duration })
    audio.onerror = () => reject(new Error('Browser could not decode Wizard audio output'))
    audio.src = url
  }), { url: output!.url, mediaKind: kind })
  expect(Object.values(decoded).every(value => Number.isFinite(value) && value > 0)).toBeTruthy()

  const started = Number(task?.started_at || task?.created_at || 0)
  const completed = Number(task?.completed_at || 0)
  const timing = {
    started_at: task?.started_at ?? null,
    completed_at: task?.completed_at ?? null,
    elapsed_seconds: started > 0 && completed > started ? completed - started : null,
  }
  await info.attach(`${label}-task.json`, { body: JSON.stringify(task, null, 2), contentType: 'application/json' })
  await info.attach(`${label}-metadata.json`, { body: JSON.stringify(metadata, null, 2), contentType: 'application/json' })
  await info.attach(`${label}-timing.json`, { body: JSON.stringify({ timing, decoded, bytes: bytes.length }, null, 2), contentType: 'application/json' })
  await info.attach(`${label}-output${kind === 'image' ? '.png' : '.wav'}`, { body: bytes, contentType: kind === 'image' ? 'image/png' : 'audio/wav' })
  return { task, output, metadata, bytes, decoded, timing }
}

async function attachEvidence(page: Page, request: APIRequestContext, testInfo: TestInfo, transcript: string) {
  const config = await liveConfig(request, test.info())
  const workspace = String(config.execution_workspace)
  const [tasks, stories] = await Promise.all([
    json(request, `/api/v1/tasks?status=all&workspace=${encodeURIComponent(workspace)}`),
    json(request, `/api/v1/stories/library?workspace=${encodeURIComponent(workspace)}`),
  ])
  const wizardTrace = await page.evaluate(() => (
    window as Window & { __HOCUSPOCUS_WIZARD_TRACE__?: Array<Record<string, unknown>> }
  ).__HOCUSPOCUS_WIZARD_TRACE__ || [])
  await testInfo.attach('wizard-transcript.txt', { body: transcript, contentType: 'text/plain' })
  await testInfo.attach('wizard-command-trace.json', { body: JSON.stringify(wizardTrace, null, 2), contentType: 'application/json' })
  await testInfo.attach('canonical-tasks.json', { body: JSON.stringify(tasks, null, 2), contentType: 'application/json' })
  await testInfo.attach('story-library.json', { body: JSON.stringify(stories, null, 2), contentType: 'application/json' })
  await testInfo.attach('final-ui.png', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' })
}

const isolationByPage = new WeakMap<Page, Awaited<ReturnType<typeof isolateLiveWorkspace>>>()
test.afterEach(async ({ page, request }, info) => {
  if (info.status !== 'passed' && info.status !== 'skipped') {
    try {
      await attachEvidence(page, request, info, (await wizardPanel(page).textContent()) || '')
    } catch (error) {
      await info.attach('evidence-observation-error.txt', { body: String(error), contentType: 'text/plain' })
    }
  }
  await isolationByPage.get(page)?.evidence()
})

test.beforeEach(async ({ page, request }) => {
  const isolation = await isolateLiveWorkspace(page, request, test.info())
  isolationByPage.set(page, isolation)
  const hydrated = page.waitForResponse(response => {
    const url = new URL(response.url())
    return url.pathname === '/api/v1/wizard/conversations' && url.searchParams.get('workspace') === isolation.workspace && response.request().method() === 'GET' && response.ok()
  })
  await openApp(page)
  await hydrated
  await expect(wizardPanel(page).getByText(`Workspace: ${isolation.workspace}`, { exact: true })).toBeVisible()
})

test('wizard: Studio UI → canonical queue → generated video', async ({ page, request }, testInfo) => {
  test.skip(!['smoke', 'full', 'studio'].includes(scenario), `scenario=${scenario}`)
  const config = await liveConfig(request, test.info())
  const before = await rootTaskIds(request, String(config.execution_workspace))
  const transcript = await ask(page, expectedMode === 'plan'
    ? 'Abre Studio → Video y rellena visiblemente el formulario con un plano de 5 segundos de un mago programador ante servidores. No lo generes.'
    : 'Abre Studio → Video, rellena visiblemente el formulario con un plano de 5 segundos de un mago programador ante servidores, y genéralo ahora. Decide tú los demás valores compatibles.')
  if (expectedMode !== 'plan') {
    const workspace = String(config.execution_workspace)
    const taskId = await waitForTerminalRoot(request, workspace, before, 'completed')
    const tasks = await json(request, `/api/v1/tasks?status=all&workspace=${encodeURIComponent(workspace)}`) as {
      tasks: Array<{ id: string; result_refs?: string[]; metadata?: Record<string, unknown> }>
    }
    const task = tasks.tasks.find(item => item.id === taskId)
    const wizardTrace = await page.evaluate(() => (
      window as Window & { __HOCUSPOCUS_WIZARD_TRACE__?: Array<Record<string, unknown>> }
    ).__HOCUSPOCUS_WIZARD_TRACE__ || []) as Array<{ results?: Array<{ action?: { type?: string }; command?: { commandId?: string }; report?: { taskId?: string } }> }>
    const generationResult = wizardTrace.flatMap(item => item.results || [])
      .find(item => item.action?.type === 'start_generation')
    const commandId = generationResult?.command?.commandId
    expect(commandId).toBeTruthy()
    expect(generationResult?.report?.taskId).toBe(taskId)
    expect(task?.metadata?.actor).toBe('wizard')
    expect(task?.metadata?.capability).toBe('start_generation')
    expect(task?.metadata?.command_id).toBe(commandId)
    const outputName = task?.result_refs?.[0]
    expect(outputName).toBeTruthy()
    const metadata = await json(
      request,
      `/api/v1/outputs/${encodeURIComponent(String(outputName))}/metadata?workspace=${encodeURIComponent(workspace)}`,
    ) as { origin?: Record<string, unknown>; execution?: Record<string, unknown> }
    expect(metadata.origin?.actor).toBe('wizard')
    expect(metadata.origin?.capability).toBe('start_generation')
    expect(metadata.origin?.output_folder).toBe(workspace)
    expect(metadata.origin).not.toHaveProperty('workspace_id')
    expect(metadata.execution?.command_id).toBe(commandId)
  } else {
    expect(await rootTaskIds(request, String(config.execution_workspace))).toEqual(before)
  }
  expect(transcript).toMatch(/Studio|vídeo|video/i)
  await expect(page.getByRole('button', { name: 'Direct generation', exact: true })).toBeVisible()
  await expect(page.getByPlaceholder('Describe your video...')).not.toHaveValue('')
  await attachEvidence(page, request, testInfo, transcript)
})

test('wizard: Ask to the Wizard real image and music outputs', async ({ page, request }, testInfo) => {
  test.skip(scenario !== 'wizard-media', `scenario=${scenario}`)
  const config = await liveConfig(request, test.info())
  const workspace = String(config.execution_workspace)
  const imagePrompt = [
    'Generate a fresh image now through Ask to the Wizard.',
    'Open Studio → Image and fill a fresh image generation form for one wide product-style illustration of Tentri, the LogSentinel observatory mascot, supervising amber log streams in a dark terminal room.',
    'Use the installed local Flux 2 Klein 9B model exactly when it is available, one 16:9 image.',
    'Do not reuse an existing gallery output and do not ask me for decisions.',
  ].join(' ')
  const beforeImage = await rootTaskIds(request, workspace)
  const imageTranscript = await ask(page, imagePrompt)
  const image = await waitForWizardMedia(page, request, testInfo, workspace, beforeImage, 'wizard-image', 'image')
  expect(image.task.model).toMatch(/Flux 2 Klein 9B/i)

  const musicPrompt = [
    'Generate a fresh instrumental music track now through Ask to the Wizard.',
    'Open Studio → Audio → Music and fill a fresh form for a 20-second playful chiptune observatory ident: warm synth bass, bright arpeggios, crisp terminal beeps and a confident rising finish, with no vocals.',
    'Use the installed local ACE-Step 1.5 XL SFT LM_4B model exactly when it is available, and set the duration to 20 seconds.',
    'Create a new audio task; do not reuse the image or any earlier audio output and do not ask me for decisions.',
  ].join(' ')
  const beforeMusic = await rootTaskIds(request, workspace)
  const musicTranscript = await ask(page, musicPrompt)
  const music = await waitForWizardMedia(page, request, testInfo, workspace, beforeMusic, 'wizard-music', 'audio')
  expect(music.task.model).toMatch(/ACE-Step/i)
  expect((music.task.metadata?.generation_details as Record<string, unknown> | undefined)?.duration_seconds).toBe(20)
  expect(music.decoded.duration).toBeGreaterThan(15)
  expect(music.decoded.duration).toBeLessThan(25)

  const trace = await page.evaluate(() => (
    window as Window & { __HOCUSPOCUS_WIZARD_TRACE__?: Array<Record<string, unknown>> }
  ).__HOCUSPOCUS_WIZARD_TRACE__ || []) as Array<{
    question?: string
    turn?: { actions?: Array<{ type?: string }> }
    results?: Array<{ action?: { type?: string }; command?: { commandId?: string }; report?: { taskId?: string } }>
  }>
  const imageTurn = trace.find(entry => entry.question === imagePrompt)
  const musicTurn = trace.find(entry => entry.question === musicPrompt)
  expect(imageTurn?.turn?.actions?.map(action => action.type)).toEqual(expect.arrayContaining(['prepare_image', 'start_generation']))
  expect(musicTurn?.turn?.actions?.map(action => action.type)).toEqual(expect.arrayContaining(['prepare_audio', 'start_generation']))
  for (const [entry, resultId] of [[imageTurn, image.task.id], [musicTurn, music.task.id]] as const) {
    const generation = entry?.results?.find(result => result.action?.type === 'start_generation')
    expect(generation?.command?.commandId).toBeTruthy()
    expect(generation?.report?.taskId).toBe(resultId)
  }
  await testInfo.attach('wizard-image-prompt.txt', { body: imagePrompt, contentType: 'text/plain' })
  await testInfo.attach('wizard-music-prompt.txt', { body: musicPrompt, contentType: 'text/plain' })
  await testInfo.attach('wizard-media-run.json', {
    body: JSON.stringify({ workspace, image, music }, null, 2),
    contentType: 'application/json',
  })
  await attachEvidence(page, request, testInfo, `${imageTranscript}\n\n--- MUSIC ---\n\n${musicTranscript}`)
})

test('wizard: UI locale, conversation, content, speech and provider prompt stay independent', async ({ page, request }, testInfo) => {
  test.skip(!['full', 'language'].includes(scenario), `scenario=${scenario}`)
  const transcript = await ask(page,
    'Réponds-moi en français. Ouvre Studio → Vidéo et remplis visiblement un plan de cinq secondes: an English technical description of an adult animated fantasy observatory, but the wizard must say exactly "¡Hola, mundo!" in Spanish. Ne génère rien.',
  )
  const trace = await page.evaluate(() => (
    window as Window & { __HOCUSPOCUS_WIZARD_TRACE__?: Array<Record<string, unknown>> }
  ).__HOCUSPOCUS_WIZARD_TRACE__ || []) as Array<{
    turn?: { conversationLanguage?: string; actions?: Array<{
      type?: string
      languageIntent?: {
        conversationLanguage?: string
        contentLanguage?: string
        spokenLanguage?: string
        technicalPromptLanguage?: string
        verbatimSegments?: Array<{ kind?: string; text?: string; language?: string }>
      }
    }> }
  }>
  const turn = trace.at(-1)?.turn
  const prepare = turn?.actions?.find(action => action.type === 'prepare_video')
  expect(turn?.conversationLanguage).toBe('fr')
  expect(prepare?.languageIntent?.spokenLanguage?.toLocaleLowerCase()).toMatch(/^(?:es(?:-|$)|.*espa|.*spanish)/)
  expect(prepare?.languageIntent?.technicalPromptLanguage).toBe('en')
  expect(prepare?.languageIntent?.verbatimSegments).toContainEqual(expect.objectContaining({
    kind: 'dialogue', text: '¡Hola, mundo!', language: 'es',
  }))
  await expect(page.locator('[lang="fr"]').last()).toBeVisible()
  const visiblePrompt = page.getByPlaceholder('Describe your video...')
  await expect(visiblePrompt).toHaveValue(/HOCUSPOCUS LANGUAGE CONTRACT/)
  await expect(visiblePrompt).toHaveValue(/Technical direction language: English/)
  await expect(visiblePrompt).toHaveValue(/¡Hola, mundo!/)
  expect(transcript).toMatch(/vidéo|prépar|studio/i)
  await attachEvidence(page, request, testInfo, transcript)
})

test('wizard: vocal Spanish song → selected version → music-video Director', async ({ page, request }, testInfo) => {
  test.skip(!['full', 'music-video'].includes(scenario), `scenario=${scenario}`)
  const title = `E2E Himno Sysadmin ${Date.now()}`
  const config = await liveConfig(request, test.info())
  const firstTranscript = await ask(page,
    `Crea desde cero en Story Lab un proyecto de tipo videoclip titulado exactamente "${title}". Rellena visiblemente una canción vocal completa de 20 segundos en español, heavy metal ochentero, voz ronca y coro grave, con secciones [Verse], [Chorus], [Bridge] y [Outro]. Usa ACE-Step 1.5 XL local y genera la primera versión de la canción. Todavía no prepares el videoclip. No me pidas decisiones: invéntalo todo.`,
  )
  await waitForStorySongVersion(request, String(config.execution_workspace), title, 1)
  const beforeV2 = await rootTaskIds(request, String(config.execution_workspace))
  const beforeDirector = await directorPipelineIds(request)
  const secondTranscript = await ask(page,
    `En el proyecto exacto "${title}", conserva la letra española, intensifica el estilo con guitarras gemelas y coro más grave, genera una nueva versión v2 con ACE-Step, y usa por ID esa nueva versión seleccionada —no la v1— para preparar el videoclip con estética de animación adulta fantástica de 1981 y ejecutarlo ahora en Director.`,
  )
  await waitForStorySongVersion(request, String(config.execution_workspace), title, 2)
  await waitForTerminalRoot(request, String(config.execution_workspace), beforeV2, 'completed')
  await waitForCompletedDirectorPipeline(request, beforeDirector)
  const transcript = `${firstTranscript}\n\n--- VERSION 2 + DIRECTOR ---\n\n${secondTranscript}`
  const library = await json(request, `/api/v1/stories/library?workspace=${encodeURIComponent(String(config.execution_workspace))}`) as {
    projects: Record<string, { title: string; projectType?: string; languageIntent?: { technicalPromptLanguage?: string; spokenLanguage?: string }; music?: { cues?: Array<{ style?: string; lyrics?: string; selectedCandidateId?: string; candidates?: Array<{ id: string; version?: number }> }> } }>
  }
  const project = Object.values(library.projects).find(item => item.title === title)
  expect(project?.projectType).toBe('music_video')
  expect(project?.languageIntent?.technicalPromptLanguage).toBe('en')
  expect(project?.music?.cues?.some(cue => Boolean(cue.lyrics?.trim()))).toBeTruthy()
  const cue = project?.music?.cues?.find(item => Boolean(item.selectedCandidateId))
  expect(cue?.style?.trim().length).toBeGreaterThan(10)
  expect(cue?.candidates?.length).toBeGreaterThanOrEqual(2)
  const latest = [...(cue?.candidates || [])].sort((left, right) => Number(right.version || 0) - Number(left.version || 0))[0]
  expect(cue?.selectedCandidateId).toBe(latest?.id)
  await expect(page.getByRole('tab', { name: 'Director', exact: true })).toHaveAttribute('aria-selected', 'true')
  await attachEvidence(page, request, testInfo, transcript)
})

test('wizard: one-turn new song request never reuses the selected music-video project', async ({ page, request }, testInfo) => {
  test.skip(scenario !== 'music-video-new', `scenario=${scenario}`)
  const title = `E2E Linus Libre ${Date.now()}`
  const config = await liveConfig(request, test.info())
  const workspace = String(config.execution_workspace)
  const beforeStories = await storyProjectIds(request, workspace)
  const beforeTasks = await rootTaskIds(request, workspace)
  const beforeDirector = await directorPipelineIds(request)
  const transcript = await ask(page,
    `Hazme un videoclip titulado exactamente "${title}" de una canción de 20 segundos en la que Linus Torvalds sea el protagonista y luche contra el software propietario, siempre en animación dibujada inspirada en la película de animación adulta Heavy Metal de 1981. Escribe la letra vocal, genera la canción con ACE-Step 1.5 XL y ejecuta el videoclip. Invéntalo todo y no reutilices ninguna canción anterior.`,
  )
  const created = await waitForNewStoryProject(request, workspace, beforeStories, title)
  const projectId = created.id
  await waitForTerminalRoot(request, workspace, beforeTasks, 'completed')
  await waitForCompletedDirectorPipeline(request, beforeDirector)
  // Creation is observable before the later song/staging mutations complete.
  // Assert the final persisted object, not that deliberately early snapshot.
  const finalLibrary = await json(request, `/api/v1/stories/library?workspace=${encodeURIComponent(workspace)}`) as {
    projects: Record<string, {
      title?: string
      projectType?: string
      premise?: string
      synopsis?: string
      creativeBrief?: { generalIdea?: string }
      music?: { cues?: Array<{ lyrics?: string; selectedCandidateId?: string; candidates?: Array<{ id?: string }> }> }
    }>
  }
  const project = finalLibrary.projects[projectId]
  expect(project).toBeTruthy()
  const authoredText = [
    project.title,
    project.premise,
    project.synopsis,
    project.creativeBrief?.generalIdea,
  ].filter(Boolean).join(' ')
  expect(project.projectType).toBe('music_video')
  expect(project.title).toBe(title)
  expect(authoredText).toMatch(/Linus Torvalds/i)
  expect(authoredText).not.toMatch(/Quemar Tokens/i)
  const cue = project.music?.cues?.find(candidate => Boolean(candidate.selectedCandidateId))
  expect(cue?.lyrics?.trim()).toMatch(/\S/)
  expect(cue?.selectedCandidateId).toBeTruthy()
  expect(cue?.candidates?.some(candidate => candidate.id === cue.selectedCandidateId)).toBeTruthy()
  const wizardTrace = await page.evaluate(() => (
    window as Window & { __HOCUSPOCUS_WIZARD_TRACE__?: Array<Record<string, unknown>> }
  ).__HOCUSPOCUS_WIZARD_TRACE__ || []) as Array<{
    turn?: { actions?: Array<{ type?: string; title?: string; targetStoryTitle?: string; songTitle?: string; cueTitle?: string }> }
    results?: Array<{
      action?: { type?: string; title?: string; targetStoryId?: string; targetStoryTitle?: string; songTitle?: string; cueId?: string; cueTitle?: string; candidateId?: string; productionId?: string }
      report?: { target?: { id?: string; title?: string } }
    }>
  }>
  const traceEntry = wizardTrace.at(-1)
  const actions = traceEntry?.turn?.actions || []
  expect(actions.map(action => action.type)).toEqual([
    'create_story', 'configure_story_song', 'generate_story_song', 'stage_story_music_video', 'start_director_production',
  ])
  const create = actions[0]
  // `turn.actions` is the provider's proposed plan and is allowed to omit
  // IDs/titles that only exist after create_story executes. The contract to
  // assert is the hydrated action carried by each result/command, because
  // that is what the UI adapter really ran and what a resumed workflow uses.
  const hydrated = (traceEntry?.results || []).map(result => result.action || {})
  expect(hydrated.map(action => action.type)).toEqual(actions.map(action => action.type))
  expect(hydrated[1]?.targetStoryTitle).toBe(create?.title)
  expect(hydrated[2]?.targetStoryTitle).toBe(create?.title)
  expect(hydrated[3]?.targetStoryTitle).toBe(create?.title)
  expect(hydrated[1]?.targetStoryId).toBe(traceEntry?.results?.[0]?.report?.target?.id)
  expect(hydrated[2]?.targetStoryId).toBe(traceEntry?.results?.[0]?.report?.target?.id)
  expect(hydrated[3]?.targetStoryId).toBe(traceEntry?.results?.[0]?.report?.target?.id)
  expect(hydrated[2]?.cueId).toBe(traceEntry?.results?.[1]?.report?.target?.id)
  expect(hydrated[3]?.cueId).toBe(traceEntry?.results?.[1]?.report?.target?.id)
  expect(hydrated[3]?.candidateId).toBe(traceEntry?.results?.[2]?.report?.target?.id)
  expect(hydrated[4]?.productionId).toBe(traceEntry?.results?.[3]?.report?.target?.id)
  await expect(page.getByRole('tab', { name: 'Director', exact: true })).toHaveAttribute('aria-selected', 'true')
  await attachEvidence(page, request, testInfo, transcript)
})

test('wizard: multi-page comic is created and all panels are generated', async ({ page, request }, testInfo) => {
  test.skip(!['full', 'comic'].includes(scenario), `scenario=${scenario}`)
  const title = `E2E Comic ${Date.now()}`
  const config = await liveConfig(request, test.info())
  const before = await rootTaskIds(request, String(config.execution_workspace))
  const transcript = await ask(page,
    `Crea desde cero un cómic titulado exactamente "${title}" con 3 páginas y 4 viñetas distintas por página sobre una maga que repara una red encantada. Rellena la UI de Comics con todas las páginas y genera ahora todas las imágenes usando el proveedor local.`,
  )
  await waitForTerminalRoot(request, String(config.execution_workspace), before, 'completed')
  expect(transcript).toMatch(/cómic|comic|página/i)
  await expect(page.getByRole('tab', { name: 'Comics' })).toHaveAttribute('aria-selected', 'true')
  await wizardPanel(page).getByRole('button', { name: 'Close Ask to the Wizard', exact: true }).click()
  const jsonDownload = page.waitForEvent('download')
  await page.getByRole('button', { name: 'JSON', exact: true }).click()
  const exported = await jsonDownload
  const jsonPath = testInfo.outputPath(exported.suggestedFilename())
  await exported.saveAs(jsonPath)
  const comic = JSON.parse(await fs.readFile(jsonPath, 'utf8')) as ComicProject
  expect(comic.title).toBe(title)
  expect(comic.pages).toHaveLength(3)
  for (const comicPage of comic.pages) {
    const panels = comicPage.elements.filter(element => element.type === 'panel' && !element.parentId)
    expect(panels).toHaveLength(4)
    for (const panel of panels) {
      const art = comicPage.elements.find(element => element.type === 'image' && element.parentId === panel.id)
      expect(art?.type).toBe('image')
      if (art?.type === 'image') expect(comic.assets[art.assetId]?.source).toBeTruthy()
    }
  }
  expect(comic.director?.completedPanelIds).toHaveLength(12)
  expect(comic.director?.failedPanelIds || []).toHaveLength(0)
  const pdfDownload = page.waitForEvent('download', { timeout: 120_000 })
  await page.getByRole('button', { name: 'PDF', exact: true }).click()
  const pdf = await pdfDownload
  const pdfPath = testInfo.outputPath(pdf.suggestedFilename())
  await pdf.saveAs(pdfPath)
  const bytes = await fs.readFile(pdfPath)
  expect(bytes.subarray(0, 5).toString()).toBe('%PDF-')
  expect(bytes.length).toBeGreaterThan(10_000)
  await testInfo.attach('comic-export.json', { path: jsonPath, contentType: 'application/json' })
  await testInfo.attach('comic-export.pdf', { path: pdfPath, contentType: 'application/pdf' })
  await attachEvidence(page, request, testInfo, transcript)
})

test('wizard: Series Lab episode form is visibly populated', async ({ page, request }, testInfo) => {
  test.skip(!['full', 'series'].includes(scenario), `scenario=${scenario}`)
  const title = `E2E Episodio ${Date.now()}`
  const created = await ask(page,
    `Abre Series Lab, crea una serie de comedia tecnológica y un episodio titulado exactamente "${title}". Inventa y rellena visiblemente premisa, personajes, localizaciones y outline. Déjalo guardado; no generes imágenes ni vídeo.`,
  )
  const planned = await ask(page, `En el episodio exacto "${title}", inicia ahora el plan completo narrativo y técnico con el LLM, con al menos 4 planos. Todavía no apliques el resultado; no renderices imágenes, audio ni vídeo.`)
  const trace = await page.evaluate(() => (window as Window & { __HOCUSPOCUS_WIZARD_TRACE__?: Array<{ results?: Array<{ action?: { type?: string }; report?: { taskId?: string } }> }> }).__HOCUSPOCUS_WIZARD_TRACE__ || [])
  const jobId = trace.flatMap(turn => turn.results || []).find(result => result.action?.type === 'generate_series_plan')?.report?.taskId
  expect(jobId).toBeTruthy()
  await expect.poll(async () => (await json(request, `/api/v1/series/plan/jobs/${encodeURIComponent(jobId!)}`)).status,
    { timeout: 10 * 60_000, intervals: [1000, 5000] }).toMatch(/^(completed|failed|cancelled)$/)
  const plan = await json(request, `/api/v1/series/plan/jobs/${encodeURIComponent(jobId!)}`)
  expect(plan.status, JSON.stringify(plan)).toBe('completed')
  await testInfo.attach('completed-series-plan.json', { body: JSON.stringify(plan, null, 2), contentType: 'application/json' })
  const applied = await ask(page, `Aplica ahora al episodio exacto "${title}" la propuesta ya completada con jobId "${jobId}". No generes otra propuesta ni renderices medios.`)
  const transcript = `${created}\n\n--- PLAN ---\n\n${planned}\n\n--- APPLY ---\n\n${applied}`
  expect(transcript).toMatch(/Series Lab|episodio|serie/i)
  await expect(page.getByRole('tab', { name: 'Series Lab' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByLabel('Series Lab workspace')).toContainText(title)
  const config = await liveConfig(request, test.info())
  const library = await json(request, `/api/v1/series/library?workspace=${encodeURIComponent(String(config.execution_workspace))}`) as SeriesLibrary
  const series = Object.values(library.seriesById).find(item => Object.values(item.episodesById).some(episode => episode.title === title))
  const episode = Object.values(series?.episodesById || {}).find(item => item.title === title)
  expect(series?.characters.length).toBeGreaterThan(0)
  expect(series?.locations.length).toBeGreaterThan(0)
  expect(episode?.premise).toMatch(/\S/)
  expect(episode?.outline.beats.length).toBeGreaterThan(0)
  expect(episode?.shots.length).toBeGreaterThanOrEqual(4)
  await testInfo.attach('persisted-series-library.json', { body: JSON.stringify(library, null, 2), contentType: 'application/json' })
  await attachEvidence(page, request, testInfo, transcript)
})

test('wizard: injected executor failure remains observable and retryable', async ({ page, request }, testInfo) => {
  test.skip(scenario !== 'failure', `scenario=${scenario}`)
  const config = await liveConfig(request, test.info())
  const workspace = String(config.execution_workspace)
  const beforeFailure = await rootTaskIds(request, workspace)
  const transcript = await ask(page,
    'Abre Studio → Audio, rellena una canción instrumental de prueba y genérala ahora.',
    { allowFailure: true },
  )
  await expect.poll(async () => {
    const payload = await json(request, `/api/v1/tasks?status=all&workspace=${encodeURIComponent(workspace)}`) as {
      tasks: Array<{ id: string; parent_id?: string | null; status: string }>
    }
    return payload.tasks.find(item => !item.parent_id && !beforeFailure.has(item.id))?.status || ''
  }, { timeout: 30_000 }).toBe('failed')
  const activityButton = page.getByRole('button', { name: 'Activity', exact: true })
  if (await activityButton.getAttribute('aria-expanded') !== 'true') await activityButton.click()
  await expect(page.getByTitle('Injected simulated audio executor failure', { exact: true })).toBeVisible()
  if (await activityButton.getAttribute('aria-expanded') === 'true') await activityButton.click()
  if (!await wizardPanel(page).isVisible()) await page.getByRole('button', { name: 'Expand Ask to the Wizard' }).click()
  await expect(wizardPanel(page)).toBeVisible()
  const beforeRetry = await rootTaskIds(request, workspace)
  const retryTranscript = await ask(
    page,
    'Abre Studio → Audio, rellena una canción instrumental de segundo intento con piano y sintetizador, y genérala ahora como una tarea nueva.',
    { allowFailure: true },
  )
  await waitForTerminalRoot(request, workspace, beforeRetry)
  const afterRetry = await json(request, `/api/v1/tasks?status=all&workspace=${encodeURIComponent(workspace)}`) as {
    tasks: Array<{ id: string; status: string }>
  }
  expect(afterRetry.tasks.some(item => !beforeRetry.has(item.id) && item.status === 'completed')).toBeTruthy()
  await attachEvidence(page, request, testInfo, `${transcript}\n\n--- RETRY ---\n\n${retryTranscript}`)
})

test('wizard: a queued simulated generation can be cancelled from the visible Activity UI', async ({ page, request }, testInfo) => {
  test.skip(scenario !== 'cancel', `scenario=${scenario}`)
  const config = await liveConfig(request, test.info())
  expect(config.execution_mode).toBe('simulate')
  expect(Number(config.execution_simulation_step_delay || 0)).toBeGreaterThanOrEqual(0.5)
  const workspace = String(config.execution_workspace)
  const before = await rootTaskIds(request, workspace)
  const transcript = await ask(
    page,
    'Abre Studio → Video, rellena un clip de prueba de un reloj mágico y lánzalo ahora. No esperes a que termine para responder.',
  )
  await page.getByRole('button', { name: 'Activity', exact: true }).click()
  await page.getByRole('button', { name: 'Cancel', exact: true }).first().click()
  await expect.poll(async () => {
    const payload = await json(request, `/api/v1/tasks?status=all&workspace=${encodeURIComponent(workspace)}`) as {
      tasks: Array<{ id: string; parent_id?: string | null; status: string }>
    }
    return payload.tasks.find(item => !item.parent_id && !before.has(item.id))?.status || ''
  }, { timeout: 30_000 }).toBe('cancelled')
  await attachEvidence(page, request, testInfo, transcript)
})

test('wizard: workspace switching refreshes browser context while preserving global selection', async ({ page, request }, testInfo) => {
  test.skip(scenario !== 'workspace', `scenario=${scenario}`)
  const config = await liveConfig(request, test.info())
  const primary = String(config.execution_workspace)
  const secondary = `${primary}_alt`
  const first = await ask(
    page,
    `Crea el workspace exacto "${secondary}" si no existe y cámbiate a él. No generes nada.`,
  )
  await expect(wizardPanel(page)).toContainText(`Workspace: ${secondary}`)
  expect(isolationByPage.get(page)?.selected()).toBe(secondary)
  const second = await ask(page, `Vuelve ahora al workspace exacto "${primary}". No generes nada.`)
  await expect(wizardPanel(page)).toContainText(`Workspace: ${primary}`)
  expect(isolationByPage.get(page)?.selected()).toBe(primary)
  await attachEvidence(page, request, testInfo, `${first}\n\n--- SWITCH BACK ---\n\n${second}`)
})
