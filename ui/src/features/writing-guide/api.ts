import { BASE } from '../../api/http'
import type { GuideAction, GuideResult, GuideScope } from './model'

export type GuideProvider = { provider: string; model: string; baseUrl: string }
export type GuideRequest = {
  scope: GuideScope; action: GuideAction; questionId: string; language: string
  values: Record<string, string>; context: Record<string, unknown>; provider: GuideProvider
}

export async function proposeWriting(request: GuideRequest, signal: AbortSignal): Promise<GuideResult> {
  const { provider, ...body } = request
  const response = await fetch(`${BASE}/api/v1/writing-guide/propose`, {
    method: 'POST', signal, headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...body, writingProvider: provider.provider, writingModel: provider.model, writingBaseUrl: provider.baseUrl }),
  })
  const result = await response.json()
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Writing request failed')
  return result
}
