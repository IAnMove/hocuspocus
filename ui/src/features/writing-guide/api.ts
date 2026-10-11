import { BASE } from '../../api/http'
import type { GuideAction, GuideResult, GuideScope } from './model'

export type GuideProvider = { provider: string; model: string; baseUrl: string }
export type GuideRequest = {
  scope: GuideScope; action: GuideAction; questionId: string; language: string
  values: Record<string, string>; context: Record<string, unknown>; provider: GuideProvider
}

const errorCodes = ['invalidRequest', 'invalidProposal', 'providerFailed', 'network', 'failed'] as const
export type GuideErrorCode = typeof errorCodes[number]
export class WritingGuideError extends Error {
  readonly code: GuideErrorCode
  constructor(code: GuideErrorCode) { super(code); this.code = code }
}

export async function proposeWriting(request: GuideRequest, signal: AbortSignal): Promise<GuideResult> {
  const { provider, ...body } = request
  const response = await fetch(`${BASE}/api/v1/writing-guide/propose`, {
    method: 'POST', signal, headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...body, writingProvider: provider.provider, writingModel: provider.model, writingBaseUrl: provider.baseUrl }),
  }).catch(() => { throw new WritingGuideError('network') })
  const result = await response.json().catch(() => { throw new WritingGuideError('failed') })
  if (!response.ok) {
    const code = result?.detail?.code
    throw new WritingGuideError(errorCodes.includes(code) ? code : 'failed')
  }
  return result
}
