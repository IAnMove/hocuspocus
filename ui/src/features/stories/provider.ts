import type { ProductionProfile } from '../../types'
import type { StoryProject, StoryWritingProvider } from './types'

export type ResolvedStoryWritingProvider = {
  provider: StoryWritingProvider
  model: string
  baseUrl: string
}

const DEFAULT_BASE_URLS: Partial<Record<StoryWritingProvider, string>> = {
  minimax: 'https://api.minimax.io/v1',
  openai: 'https://api.openai.com',
  deepseek: 'https://api.deepseek.com',
}

function normalizeProfileProvider(value: ProductionProfile['text']['provider']): StoryWritingProvider {
  if (
    value === 'minimax'
    || value === 'openai'
    || value === 'deepseek'
    || value === 'openai-compatible'
  ) return value
  return 'maestro'
}

/**
 * Resolves the Story Lab writing provider once for both the UI and request payloads.
 * Explicit Story overrides win; a global profile is mapped without collapsing
 * DeepSeek or OpenAI-compatible configurations into Maestro.
 */
export function resolveStoryWritingProvider(
  profile: ProductionProfile,
  project: Pick<StoryProject, 'provider'>,
): ResolvedStoryWritingProvider {
  if (!project.provider.useGlobalProfile) {
    return {
      provider: project.provider.writingProvider,
      model: project.provider.writingModel,
      baseUrl: project.provider.writingBaseUrl,
    }
  }

  const provider = normalizeProfileProvider(profile.text.provider)
  return {
    provider,
    model: profile.text.model,
    // OpenAI-compatible URLs are configured on the Story override because the
    // global ProductionProfile intentionally stores only provider and model.
    baseUrl: provider === 'openai-compatible'
      ? project.provider.writingBaseUrl
      : DEFAULT_BASE_URLS[provider] || '',
  }
}
