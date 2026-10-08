import { cancelJob, fetchJobStatus, getFileUrl, submitGeneration } from '../../api/client'
import { checkAccent, checkSpeech, type AccentCheck, type SpeechCheck } from '../../api/characters'
import { awaitSpeechOutput } from '../../lib/sceneSpeech'
import type { CustomCharacterVoice } from '../../lib/characterVoice'
import type { SpokenLanguage } from '../../lib/speechLanguage'

export const VOICE_DESIGN_MODEL = 'qwen3_tts_voicedesign'
export const REFERENCE_VOICE_MODEL = 'qwen3_tts_base'
export const VOICE_CANDIDATES = 3

/** Calm, plain sentences make a steadier cloning reference than an excited line. */
export const SAMPLE_TEXT: Partial<Record<SpokenLanguage, string>> = {
  english: 'Hello. This is my normal speaking voice. I am calm, I speak clearly, and I am ready to start.',
  spanish: 'Hola. Esta es mi voz normal. Hablo con calma y con claridad, y estoy listo para empezar.',
  french: 'Bonjour. Voici ma voix normale. Je parle calmement et clairement, et je suis prêt à commencer.',
  german: 'Hallo. Das ist meine normale Stimme. Ich spreche ruhig und deutlich, und ich bin bereit anzufangen.',
  italian: 'Ciao. Questa è la mia voce normale. Parlo con calma e chiarezza, e sono pronto a iniziare.',
  portuguese: 'Olá. Esta é a minha voz normal. Falo com calma e clareza, e estou pronto para começar.',
}

export type DesignedVoice = {
  id: string
  seed: number
  status: 'generating' | 'checking' | 'ready' | 'failed'
  filename?: string
  url?: string
  check?: SpeechCheck
  accent?: AccentCheck
  error?: string
}

/** A description sets the pitch range qa.speech warns about.

Child words win, so boy, girl, niño and niña are 220–400 Hz. chico and chica stay
adult. No matching word means the take is not checked. */
export function expectedPitch(description: string): [number, number] | undefined {
  const text = description.toLowerCase()
  if (/\b(child|children|boy|girl|niño|niña|nino|nina)\b/u.test(text)) return [220, 400]
  if (/\b(female|woman|mujer|femenina|chica)\b/u.test(text)) return [165, 255]
  if (/\b(male|man|hombre|masculina|masculino|chico)\b/u.test(text)) return [85, 155]
  return undefined
}

export type VoiceDesignDependencies = {
  submitGeneration: typeof submitGeneration
  fetchJobStatus: typeof fetchJobStatus
  cancelJob: typeof cancelJob
  checkSpeech: typeof checkSpeech
  checkAccent: typeof checkAccent
  fileUrl: typeof getFileUrl
  seed: () => number
}

const defaults: VoiceDesignDependencies = {
  submitGeneration, fetchJobStatus, cancelJob, checkSpeech, checkAccent, fileUrl: getFileUrl,
  seed: () => Math.floor(Math.random() * 2_000_000_000),
}

/** Three voices from one description, each transcribed and measured as soon as it is ready. */
export async function designVoiceCandidates(request: {
  workspace: string; description: string; text: string; language: SpokenLanguage; signal: AbortSignal
  accent?: 'castilian'
  onUpdate: (voices: DesignedVoice[]) => void
}, dependencies: Partial<VoiceDesignDependencies> = {}): Promise<DesignedVoice[]> {
  const deps = { ...defaults, ...dependencies }
  const pitchRange = expectedPitch(request.description)
  const seconds = Math.min(30, Math.max(6, Math.ceil(request.text.split(/\s+/).length / 2.2) + 3))
  let voices: DesignedVoice[] = Array.from({ length: VOICE_CANDIDATES },
    (_, index) => ({ id: `voice-${index + 1}`, seed: deps.seed(), status: 'generating' }))
  const update = (id: string, patch: Partial<DesignedVoice>) => {
    voices = voices.map(voice => voice.id === id ? { ...voice, ...patch } : voice)
    request.onUpdate(voices)
  }
  request.onUpdate(voices)
  await Promise.all(voices.map(async voice => {
    try {
      const submitted = await deps.submitGeneration({
        model_type: VOICE_DESIGN_MODEL, generation_mode: 'audio', _audio_sub_mode: 'speech', prompt: request.text,
        alt_prompt: request.description, model_mode: request.language, duration_seconds: seconds, seed: voice.seed,
        video_length: 0, image_mode: 0, multi_prompts_gen_type: 2, workspace: request.workspace,
      })
      const clip = await awaitSpeechOutput(
        { prompt: request.text, model: VOICE_DESIGN_MODEL, durationSeconds: seconds, workspace: request.workspace, signal: request.signal },
        { submitGeneration: deps.submitGeneration, fetchJobStatus: deps.fetchJobStatus, cancelJob: deps.cancelJob },
        { prompt: request.text, model: VOICE_DESIGN_MODEL, jobId: submitted.job_id })
      update(voice.id, { status: 'checking', filename: clip.filename, url: deps.fileUrl(clip.filename, request.workspace) })
      const check = await deps.checkSpeech({ workspace: request.workspace, file: clip.filename, text: request.text,
        language: request.language, ...(pitchRange ? { pitchRange } : {}) })
      let accent: AccentCheck | undefined
      if (request.accent === 'castilian') {
        try {
          accent = await deps.checkAccent({ workspace: request.workspace, file: clip.filename, text: request.text })
        } catch (error) {
          check.warnings = [...(check.warnings ?? []), (error as Error).message]
        }
      }
      update(voice.id, { status: 'ready', check, accent })
    } catch (error) {
      if (request.signal.aborted) return
      update(voice.id, { status: 'failed', error: (error as Error).message })
    }
  }))
  request.signal.throwIfAborted()
  return voices
}

/** The chosen take becomes the language's reference voice: every later line is cloned from it. */
export function referenceVoice(voice: DesignedVoice, details: { name: string; text: string; language: SpokenLanguage }): CustomCharacterVoice {
  if (!voice.url) throw new Error('This voice has no recording yet.')
  return { provider: 'local', model: REFERENCE_VOICE_MODEL, voiceId: 'reference', name: details.name.slice(0, 120),
    referenceAudio: voice.url, transcript: details.text, language: details.language }
}
