#!/usr/bin/env node
/** Explicit opt-in local ACE-Step -> Story cue -> Director videoclip smoke. */

const CONFIRM_TOKEN = 'GENERATE_REAL_MEDIA'
const TERMINAL = new Set(['completed', 'failed', 'cancelled', 'interrupted'])

const clean = value => typeof value === 'string' ? value.trim() : ''
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

const SMOKE_LANGUAGE_MARKERS = {
  es: new Set(['el', 'la', 'los', 'las', 'que', 'de', 'del', 'en', 'y', 'un', 'una', 'por', 'para', 'con', 'no', 'se', 'es', 'noche', 'red', 'canta', 'reinicia']),
  en: new Set(['the', 'and', 'that', 'this', 'with', 'from', 'through', 'night', 'our', 'your', 'you', 'we', 'is', 'are', 'to', 'of', 'in', 'on', 'not', 'fight', 'sing']),
}

const foldSmokeText = value => clean(value)
  .normalize('NFKD')
  .replace(/[\u0300-\u036f]/g, '')
  .toLocaleLowerCase()

/**
 * Provider-free semantic gate used by the opt-in media smoke. A valid WAV or
 * MP4 is not evidence that the selected song survived the workflow: the
 * canonical candidate must still carry the requested language and subject.
 */
export function evaluateSmokeSongFidelity({
  lyrics = '', lyricsLanguage = '', requiredTerms = [], protectedSegments = [],
} = {}) {
  const source = clean(lyrics)
  const folded = foldSmokeText(source)
  const missingTerms = requiredTerms.filter(term => !folded.includes(foldSmokeText(term)))
  const missingProtectedSegments = protectedSegments
    .filter(segment => !source.includes(segment))
  // Quoted lyrics can intentionally use another language. Check those
  // literals separately, but exclude them from the authored-language score.
  const languageSample = protectedSegments.reduce(
    (value, segment) => value.split(segment).join(' '),
    source,
  )
  const words = languageSample.toLocaleLowerCase().match(/[\p{L}]+/gu) || []
  const language = foldSmokeText(lyricsLanguage)
  const target = language.startsWith('es') || language.includes('spanish') || language.includes('espanol') ? 'es'
    : language.startsWith('en') || language.includes('english') || language.includes('ingles') ? 'en' : ''
  const scores = Object.fromEntries(Object.entries(SMOKE_LANGUAGE_MARKERS).map(([code, markers]) => [
    code, words.reduce((score, word) => score + (markers.has(word) ? 1 : 0), 0),
  ]))
  const strongestOther = target
    ? Math.max(...Object.entries(scores).filter(([code]) => code !== target).map(([, score]) => score), 0)
    : 0
  const languageMismatch = Boolean(target && words.length >= 8 && (
    (scores[target] || 0) === 0 && strongestOther >= 2
    || strongestOther >= (scores[target] || 0) + 3 && strongestOther >= 4
  ))
  const reasons = []
  if (!source) reasons.push('the canonical candidate has no editable lyrics')
  if (missingTerms.length) reasons.push(`missing requested subject: ${missingTerms.join(', ')}`)
  if (missingProtectedSegments.length) reasons.push('a protected lyric fragment was changed')
  if (languageMismatch) reasons.push(`lyrics do not show evidence of ${lyricsLanguage}`)
  const checks = [Boolean(source), !missingTerms.length, !missingProtectedSegments.length, !languageMismatch]
  return {
    ok: reasons.length === 0,
    score: Math.round((checks.filter(Boolean).length / checks.length) * 100),
    reasons,
    missingTerms,
    missingProtectedSegments,
    languageMismatch,
  }
}

export function normalizeSmokeBaseUrl(value) {
  const raw = clean(value)
  if (!raw) throw new Error('HOCUSPOCUS_SMOKE_BASE_URL is required.')
  let parsed
  try { parsed = new URL(raw) } catch { throw new Error('HOCUSPOCUS_SMOKE_BASE_URL must be an absolute http(s) URL.') }
  if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('HOCUSPOCUS_SMOKE_BASE_URL must use http:// or https://.')
  parsed.hash = ''
  parsed.search = ''
  return parsed.toString().replace(/\/$/, '')
}

export function validateSmokeOptIn({ runGpu = false, runExternal = false, baseUrl, confirm } = {}) {
  const missing = []
  if (runGpu !== true) missing.push('RUN_GPU_TESTS=1')
  if (!clean(baseUrl)) missing.push('HOCUSPOCUS_SMOKE_BASE_URL')
  if (confirm !== CONFIRM_TOKEN) missing.push(`HOCUSPOCUS_SMOKE_CONFIRM=${CONFIRM_TOKEN}`)
  if (missing.length) throw new Error(`Level 8 is fail-closed; explicit opt-in is missing: ${missing.join(', ')}`)
  return normalizeSmokeBaseUrl(baseUrl)
}

async function requestJson(fetchImpl, baseUrl, method, route, body, signal) {
  const response = await fetchImpl(`${baseUrl}${route}`, {
    method,
    signal,
    headers: body === undefined ? undefined : { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response?.ok) {
    const detail = await response?.json?.().catch(() => null)
    throw new Error(`${method} ${route} returned HTTP ${response?.status || 'unknown'}: ${detail?.detail || detail?.error || ''}`.trim())
  }
  return response.json()
}

async function poll(fetchImpl, baseUrl, route, { signal, intervalMs, timeoutAt }) {
  for (;;) {
    const value = await requestJson(fetchImpl, baseUrl, 'GET', route, undefined, signal)
    if (TERMINAL.has(value.status)) {
      if (value.status !== 'completed') throw new Error(`${route} ended as ${value.status}: ${value.error || value.message || ''}`)
      return value
    }
    if (Date.now() >= timeoutAt) throw new Error(`Smoke timed out while polling ${route}`)
    await sleep(intervalMs)
  }
}

function smokeProject(projectId, cueId, now) {
  return {
    version: 1, id: projectId, revision: 1,
    title: 'Nightly Wizard media smoke', projectType: 'music_video',
    language: 'Español', visualStyle: 'animación fantástica heavy metal de 1981',
    premise: 'Un sysadmin mantiene viva la red al ritmo de un himno.',
    music: {
      mode: 'original', model: 'ace_step_v1_5_xl_sft_lm_4b',
      brief: 'heavy metal ochentero español', style: 'voz ronca y coro grave',
      sourceLyrics: '', lyrics: '', lyricsLanguage: 'Español', targetDurationSeconds: 15,
      candidateCount: 2, candidates: [], cues: [{
        id: cueId, kind: 'story', targetId: projectId, title: 'Himno smoke', purpose: 'Prueba nocturna',
        referenceSong: '', brief: 'Himno breve del sysadmin', style: 'heavy metal ochentero, voz ronca, coro grave',
        lyrics: '[Verse]\nGuardianes sysadmin del rack, la noche no caerá.\n[Chorus]\nReinicia, resiste, la red despertará.',
        lyricsLanguage: 'Español', lyriaPrompt: '', instrumental: false, durationSeconds: 15, candidates: [],
      }],
    },
    productions: [], createdAt: now, updatedAt: now,
  }
}

export async function runMediaSmoke({
  baseUrl, workspace = 'nightly-smoke', runGpu = false, runExternal = false, confirm,
  mediaScope = 'all',
  fetchImpl = globalThis.fetch, timeoutMs = 6 * 60 * 60 * 1000, pollIntervalMs = 5_000,
} = {}) {
  const root = validateSmokeOptIn({ runGpu, runExternal, baseUrl, confirm })
  if (typeof fetchImpl !== 'function') throw new Error('The smoke requires fetch.')
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  const timeoutAt = Date.now() + timeoutMs
  const projectId = `story-smoke-${globalThis.crypto.randomUUID()}`
  const cueId = `cue-smoke-${globalThis.crypto.randomUUID()}`
  const now = new Date().toISOString()
  try {
    const library = await requestJson(fetchImpl, root, 'GET', `/api/v1/stories/library?workspace=${encodeURIComponent(workspace)}`, undefined, controller.signal)
    const project = smokeProject(projectId, cueId, now)
    let saved = await requestJson(fetchImpl, root, 'PUT', '/api/v1/stories/library', {
      workspace, baseRevision: library.revision,
      library: { version: 2, revision: library.revision, activeId: projectId, projects: { ...library.projects, [projectId]: project } },
    }, controller.signal)

    const cue = project.music.cues[0]
    // Level 8 is an explicit local-GPU smoke: submit the same ACE-Step
    // generation contract used by Story Lab, then poll its durable job.
    const startedSong = await requestJson(fetchImpl, root, 'POST', '/api/v1/generate', {
      prompt: cue.lyrics, alt_prompt: cue.style, model_type: 'ace_step_v1_5_xl_sft_lm_4b',
      instrumental: false, duration_seconds: cue.durationSeconds, video_length: 0,
      image_mode: 0, multi_prompts_gen_type: 2, generation_mode: 'audio', workspace,
      provenance: { actor: 'system', capability: 'nightly_local_ace_smoke', project_id: projectId, cue_id: cue.id },
    }, controller.signal)
    const song = await poll(fetchImpl, root, `/api/v1/status/${encodeURIComponent(startedSong.job_id)}`, {
      signal: controller.signal, intervalMs: pollIntervalMs, timeoutAt,
    })
    const filename = clean(song.output_files?.[0])
    const audioPath = filename
    if (!audioPath) throw new Error('Song completed without a candidate audio path.')
    const candidateId = `song-smoke-${globalThis.crypto.randomUUID()}`
    const semantic = evaluateSmokeSongFidelity({
      lyrics: cue.lyrics,
      lyricsLanguage: cue.lyricsLanguage,
      requiredTerms: ['sysadmin', 'red'],
    })
    if (!semantic.ok) throw new Error(`Song semantic fidelity failed (${semantic.score}%): ${semantic.reasons.join('; ')}`)
    const canonicalCandidate = {
      id: candidateId, name: filename.split('/').at(-1), source: audioPath,
      prompt: cue.style, lyrics: cue.lyrics, provider: 'local', model: 'ace_step_v1_5_xl_sft_lm_4b',
      language: cue.lyricsLanguage,
      durationSeconds: cue.durationSeconds || 15, createdAt: new Date().toISOString(),
      taskId: song.task_id || startedSong.task_id, rootTaskId: song.root_task_id || startedSong.root_task_id,
    }
    project.music.candidates = [canonicalCandidate]
    project.music.selectedCandidateId = candidateId
    cue.candidates = [canonicalCandidate]
    cue.selectedCandidateId = candidateId
    project.updatedAt = new Date().toISOString()
    saved = await requestJson(fetchImpl, root, 'PUT', '/api/v1/stories/library', {
      workspace, baseRevision: saved.revision,
      library: { ...saved, activeId: projectId, projects: { ...saved.projects, [projectId]: project } },
    }, controller.signal)

    if (mediaScope === 'song') {
      return {
        workspace,
        identifiers: {
          projectIds: [projectId], cueIds: [cueId], outputIds: [filename],
          taskIds: [song.task_id || startedSong.task_id].filter(Boolean), pipelineIds: [],
        },
        songStatus: song.status, pipelineStatus: 'not_requested', semantic,
      }
    }

    const analysis = await requestJson(fetchImpl, root, 'POST', '/api/v1/audio/analyze', {
      audio_path: audioPath, transcribe: true, extract_vocals: true, lyrics_hint: cue.lyrics, workspace,
    }, controller.signal)
    const structure = await requestJson(fetchImpl, root, 'POST', '/api/v1/audio/plan-structure', {
      analysis, video_model: 'minimax_h3_legacy', energy_bias: 0,
    }, controller.signal)
    if (!structure.clips?.length) throw new Error('Audio structure returned no clips.')
    const startedPipeline = await requestJson(fetchImpl, root, 'POST', '/api/v1/director/pipeline/start', {
      pipeline_type: 'music_video', auto_mode: true, scene_description: project.visualStyle,
      spoken_language: 'Español', audio_path: audioPath, planned_clips: structure.clips,
      lyrics: analysis.lyrics || cue.lyrics, bpm: analysis.bpm, generation_mode: 'direct_video',
      video_model: 'minimax_h3_legacy', director_aspect_ratio: '16:9',
      video_params: { resolution: '960x544', num_inference_steps: 20, h3_model_profile: 'quality' },
      llm_provider: 'minimax', llm_model_id: 'MiniMax-M3', writing_provider: 'minimax', writing_model: 'MiniMax-M3',
      workspace,
    }, controller.signal)
    const pipelineId = startedPipeline.pipeline_id
    if (!pipelineId) throw new Error('Director start returned no pipeline_id.')
    const pipeline = await poll(fetchImpl, root, `/api/v1/director/pipeline/${encodeURIComponent(pipelineId)}`, {
      signal: controller.signal, intervalMs: pollIntervalMs, timeoutAt,
    })
    const outputIds = [...new Set([filename, ...(pipeline.output_files || [])].filter(Boolean))]
    project.productions = [{ id: pipelineId, kind: 'music_video', title: project.title, createdAt: now, sourceVersion: 1, targetId: pipelineId, status: 'staged' }]
    project.updatedAt = new Date().toISOString()
    await requestJson(fetchImpl, root, 'PUT', '/api/v1/stories/library', {
      workspace, baseRevision: saved.revision,
      library: { ...saved, activeId: projectId, projects: { ...saved.projects, [projectId]: project } },
    }, controller.signal)
    return {
      workspace,
      identifiers: {
        projectIds: [projectId], cueIds: [cueId], outputIds,
        taskIds: [song.task_id || startedSong.task_id].filter(Boolean), pipelineIds: [pipelineId],
      },
      songStatus: song.status, pipelineStatus: pipeline.status, semantic,
    }
  } finally {
    clearTimeout(timer)
  }
}

const invokedPath = process.argv[1] ? new URL(`file://${process.argv[1]}`).pathname : ''
if (invokedPath === new URL(import.meta.url).pathname) {
  try {
    const result = await runMediaSmoke({
      baseUrl: process.env.HOCUSPOCUS_SMOKE_BASE_URL,
      workspace: process.env.HOCUSPOCUS_SMOKE_WORKSPACE || 'nightly-smoke',
      runGpu: process.env.RUN_GPU_TESTS === '1', runExternal: process.env.RUN_EXTERNAL_PROVIDER_TESTS === '1',
      confirm: process.env.HOCUSPOCUS_SMOKE_CONFIRM,
      mediaScope: process.env.NIGHTLY_MEDIA_SCOPE || 'all',
      timeoutMs: Number(process.env.NIGHTLY_SMOKE_TIMEOUT_MS || 6 * 60 * 60 * 1000),
    })
    process.stdout.write(`SMOKE_RESULT ${JSON.stringify(result)}\n`)
  } catch (error) {
    process.stderr.write(`${String(error?.stack || error)}\n`)
    process.exitCode = 1
  }
}
