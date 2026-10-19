import { BASE } from '../../api/http'
import type { GuideAction, GuideResult, GuideScope } from './model'

export type GuideProvider = { provider: string; model: string; baseUrl: string }
export type GuideRequest = {
  scope: GuideScope; action: GuideAction; questionId: string; language: string
  values: Record<string, string>; context: Record<string, unknown>; provider: GuideProvider
}

const errorCodes = ['invalidRequest', 'providerConfig', 'invalidProposal', 'providerFailed', 'network', 'failed'] as const
export type GuideErrorCode = typeof errorCodes[number]
/** `detail` is the server's own hint (which setting to fix); every other code stays fully localized. */
export class WritingGuideError extends Error {
  readonly code: GuideErrorCode
  readonly detail: string
  constructor(code: GuideErrorCode, detail = '') { super(detail || code); this.code = code; this.detail = detail }
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
    const detail = code === 'providerConfig' && typeof result.detail.message === 'string' ? result.detail.message : ''
    throw new WritingGuideError(errorCodes.includes(code) ? code : 'failed', detail)
  }
  return result
}
