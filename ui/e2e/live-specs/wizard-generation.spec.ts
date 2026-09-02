import { expect, test, type APIRequestContext, type Page, type TestInfo } from '@playwright/test'

const scenario = process.env.HOCUSPOCUS_E2E_SCENARIO || 'smoke'
const expectedMode = process.env.HOCUSPOCUS_E2E_PROFILE || 'simulate'

interface SystemConfig {
  execution_mode?: string
  execution_workspace?: string
  execution_simulation_step_delay?: number
}

async function json(request: APIRequestContext, path: string) {
  let lastError: unknown
  for (let attempt = 0; attempt < 4; attempt += 1) {
    try {
      const response = await request.get(path)
      expect(response.ok(), `${path}: ${response.status()} ${await response.text()}`).toBeTruthy()
      return await response.json()
    } catch (error) {
      lastError = error
      const transient = /ECONNRESET|ECONNREFUSED|socket hang up|closed before receiving/i.test(String(error))
      if (!transient || attempt === 3) throw error
      await new Promise(resolve => setTimeout(resolve, 150 * (attempt + 1)))
    }
  }
  throw lastError
}

async function prepareWorkspace(request: APIRequestContext): Promise<SystemConfig> {
  const config = await json(request, '/api/v1/system-config') as SystemConfig
  expect(config.execution_mode).toBe(expectedMode)
  const workspace = config.execution_workspace
  expect(workspace).toBeTruthy()
  const listing = await json(request, '/api/v1/workspaces') as { workspaces: Array<{ name: string }> }
  if (!listing.workspaces.some(item => item.name === workspace)) {
    const created = await request.post('/api/v1/workspaces', { data: { name: workspace } })
    expect(created.ok(), await created.text()).toBeTruthy()
  }
  const selected = await request.put('/api/v1/workspaces/active', { data: { name: workspace } })
  expect(selected.ok(), await selected.text()).toBeTruthy()
  return config
}

function wizardPanel(page: Page) {
  return page.locator(
    '[role="dialog"][aria-label="Ask to the Wizard"], [role="region"][aria-label="Ask to the Wizard"]',
  ).first()
}

async function openApp(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('hocuspocus_welcome_seen_v1', '1')
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
  if (!await panel.isVisible()) {
    const expand = page.getByRole('button', { name: 'Expand Ask to the Wizard' })
    if (await expand.isVisible()) await expand.click()
    else await page.getByTitle('Ask to the Wizard about the app or current task queue').click()
  }
  await expect(panel).toBeVisible()
  await panel.getByRole('button', { name: 'Clear Ask to the Wizard conversation' }).click()
  await expect(panel.getByText('Saludos, creador. Soy el mago de HocusPocus', { exact: false })).toBeVisible()
}

async function ask(page: Page, prompt: string, options: { allowFailure?: boolean } = {}): Promise<string> {
  const panel = wizardPanel(page)
  const input = panel.getByPlaceholder('Ask HocusPocus for a spell…')
  await input.fill(prompt)
  await panel.getByRole('button', { name: 'Ask to the Wizard', exact: true }).click()
  await expect(input).toBeDisabled()
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
  let taskId = ''
  await expect.poll(async () => {
    const payload = await json(request, `/api/v1/tasks?status=all&workspace=${encodeURIComponent(workspace)}`) as {
      tasks: Array<{ id: string; parent_id?: string | null }>
    }
    taskId = payload.tasks.find(item => !item.parent_id && !previous.has(item.id))?.id || ''
    return taskId
  }, { timeout: 60_000, intervals: [250, 500, 1_000, 2_000] }).not.toBe('')
  let terminalStatus = ''
  await expect.poll(async () => {
    const payload = await json(request, `/api/v1/tasks?status=all&workspace=${encodeURIComponent(workspace)}`) as {
      tasks: Array<{ id: string; parent_id?: string | null; status: string }>
    }
    terminalStatus = payload.tasks.find(item => item.id === taskId)?.status || ''
    return terminalStatus
  }, { timeout: 20 * 60_000, intervals: [500, 1_000, 2_000, 5_000] }).toMatch(/completed|failed|cancelled/)
  if (expectedStatus === 'completed') expect(terminalStatus).toBe('completed')
  return taskId
}

async function attachEvidence(page: Page, request: APIRequestContext, testInfo: TestInfo, transcript: string) {
  const config = await json(request, '/api/v1/system-config') as SystemConfig
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

test.beforeEach(async ({ page, request }) => {
  const config = await prepareWorkspace(request)
  if (config.execution_mode === 'real') {
    expect(process.env.HOCUSPOCUS_E2E_CONFIRM_REAL).toBe('YES')
  }
  await openApp(page)
})

test('wizard: Studio UI → canonical queue → generated video', async ({ page, request }, testInfo) => {
  test.skip(!['smoke', 'full', 'studio'].includes(scenario), `scenario=${scenario}`)
  const config = await json(request, '/api/v1/system-config') as SystemConfig
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
  await expect(page.getByRole('button', { name: 'Studio', exact: true })).toHaveClass(/bg-toggle-active/)
  await expect(page.getByPlaceholder('Describe your video...')).not.toHaveValue('')
  await attachEvidence(page, request, testInfo, transcript)
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
  const config = await json(request, '/api/v1/system-config') as SystemConfig
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
  await expect(page.getByRole('button', { name: 'Director', exact: true })).toHaveClass(/bg-toggle-active/)
  await attachEvidence(page, request, testInfo, transcript)
})

test('wizard: multi-page comic is created and all panels are generated', async ({ page, request }, testInfo) => {
  test.skip(!['full', 'comic'].includes(scenario), `scenario=${scenario}`)
  const title = `E2E Comic ${Date.now()}`
  const config = await json(request, '/api/v1/system-config') as SystemConfig
  const before = await rootTaskIds(request, String(config.execution_workspace))
  const transcript = await ask(page,
    `Crea desde cero un cómic titulado exactamente "${title}" con 3 páginas y 4 viñetas distintas por página sobre una maga que repara una red encantada. Rellena la UI de Comics con todas las páginas y genera ahora todas las imágenes usando el proveedor local.`,
  )
  await waitForTerminalRoot(request, String(config.execution_workspace), before)
  expect(transcript).toMatch(/cómic|comic|página/i)
  await expect(page.getByRole('tab', { name: 'Comics' })).toHaveAttribute('aria-selected', 'true')
  await attachEvidence(page, request, testInfo, transcript)
})

test('wizard: Series Lab episode form is visibly populated', async ({ page, request }, testInfo) => {
  test.skip(!['full', 'series'].includes(scenario), `scenario=${scenario}`)
  const title = `E2E Episodio ${Date.now()}`
  const transcript = await ask(page,
    `Abre Series Lab, crea una serie de comedia tecnológica y un episodio titulado exactamente "${title}". Inventa y rellena visiblemente premisa, personajes, localizaciones, outline y al menos 4 planos. Déjalo guardado y preparado, sin generación pesada.`,
  )
  expect(transcript).toMatch(/Series Lab|episodio|serie/i)
  await expect(page.getByRole('tab', { name: 'Series Lab' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByLabel('Series Lab workspace')).toContainText(title)
  await attachEvidence(page, request, testInfo, transcript)
})

test('wizard: injected executor failure remains observable and retryable', async ({ page, request }, testInfo) => {
  test.skip(scenario !== 'failure', `scenario=${scenario}`)
  const config = await json(request, '/api/v1/system-config') as SystemConfig
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
  await page.getByTitle('Ask to the Wizard about the app or current task queue').click()
  await expect(page.getByRole('dialog', { name: 'Ask to the Wizard' })).toBeVisible()
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
  const config = await json(request, '/api/v1/system-config') as SystemConfig
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

test('wizard: workspace switching refreshes its visible and server context', async ({ page, request }, testInfo) => {
  test.skip(scenario !== 'workspace', `scenario=${scenario}`)
  const config = await json(request, '/api/v1/system-config') as SystemConfig
  const primary = String(config.execution_workspace)
  const secondary = `e2e_wizard_alt_${Date.now()}`
  const first = await ask(
    page,
    `Crea el workspace exacto "${secondary}" si no existe y cámbiate a él. No generes nada.`,
  )
  await expect(page.getByRole('dialog', { name: 'Ask to the Wizard' })).toContainText(`Workspace: ${secondary}`)
  expect((await json(request, '/api/v1/workspaces') as { active: string }).active).toBe(secondary)
  const second = await ask(page, `Vuelve ahora al workspace exacto "${primary}". No generes nada.`)
  await expect(page.getByRole('dialog', { name: 'Ask to the Wizard' })).toContainText(`Workspace: ${primary}`)
  expect((await json(request, '/api/v1/workspaces') as { active: string }).active).toBe(primary)
  await attachEvidence(page, request, testInfo, `${first}\n\n--- SWITCH BACK ---\n\n${second}`)
  const removed = await request.delete(`/api/v1/workspaces/${encodeURIComponent(secondary)}`)
  expect(removed.ok(), await removed.text()).toBeTruthy()
})
