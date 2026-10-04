import { setupSpeechPhonemes } from '../../api/scene3dSpeech'
import type { AgentSpeechAnalysisEngineAction } from './agentActions'

export async function setupSpeechAnalysis(action: AgentSpeechAnalysisEngineAction) {
  const result = await setupSpeechPhonemes(action.install)
  return { message: result.installed ? 'CPU phoneme lip-sync engine is installed and ready in the editor, Wizard and MCP.' : 'CPU phoneme engine is not installed. Automatic analysis uses Rhubarb when available; installation must be explicit.',
    target: { kind: 'speech_analysis_engine', id: 'phoneme', title: 'Lip-sync analysis' }, metadata: { ...result, installRequested: action.install } }
}
