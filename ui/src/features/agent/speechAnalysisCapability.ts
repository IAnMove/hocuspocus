import type { defineCapability } from './capabilityRegistry'
import type { AgentSpeechAnalysisEngineAction } from './agentActions'

export function registerSpeechAnalysisCapability(register: typeof defineCapability) {
  register<AgentSpeechAnalysisEngineAction>({
    name: 'speech_analysis_engine', title: 'Configure lip-sync analysis',
    description: 'Use the same optional CPU phoneme engine as Video3D and MCP audio.phonemes.setup. install=false reads offline status. install=true explicitly installs the pinned 1.26 GB model through the native installer; use it only when the user asks to install the engine. Analysis never downloads. No voice generation or video export.',
    useWhen: 'The user asks whether phoneme lip sync is installed or asks to install it for singing/dialogue. Then use prepare_programmatic_video with scenes.speech.prepare, exact text, language and engine=auto or phoneme.',
    parameters: ['install'], inputSchema: { type: 'object', additionalProperties: false,
      properties: { type: { const: 'speech_analysis_engine' }, install: { type: 'boolean', default: false } }, required: ['type'] },
    risk: 'edit', confirmation: 'none', progress: 'Comprobando el motor de sincronización labial…',
    resolve(raw) { return raw.install === undefined || typeof raw.install === 'boolean' ? { type: 'speech_analysis_engine', install: raw.install === true } : null },
    validate() { return [] }, async prepare(action) { return action },
    async execute(action, context) { return context.adapters.video3d.setupSpeechAnalysis(action) },
    correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
    report: { targetKind: 'speech_analysis_engine', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'video_3d', anchors: ['speech'], replay: 'atomic' },
  })
}
