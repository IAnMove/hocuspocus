import assert from 'node:assert/strict'
import test from 'node:test'

import { resolveStoryWritingProvider } from '../src/features/stories/provider.ts'

const project = (useGlobalProfile = true, overrides = {}) => ({
  provider: {
    useGlobalProfile,
    writingProvider: 'maestro',
    writingModel: 'story-local-model',
    writingBaseUrl: 'https://custom.example/v1',
    imageProvider: 'maestro',
    imageModel: 'local-image',
    ...overrides,
  },
})

test('resolves every supported global Story writing provider without collapsing it', () => {
  const cases = [
    ['minimax', 'MiniMax-M3', 'minimax', 'https://api.minimax.io/v1'],
    ['openai', 'gpt-4.1', 'openai', 'https://api.openai.com'],
    ['deepseek', 'deepseek-v4-pro', 'deepseek', 'https://api.deepseek.com'],
    ['openai-compatible', 'custom-model', 'openai-compatible', 'https://custom.example/v1'],
    ['local', 'maestro-model', 'maestro', ''],
  ]

  for (const [profileProvider, model, expectedProvider, expectedBaseUrl] of cases) {
    assert.deepEqual(
      resolveStoryWritingProvider(
        { text: { provider: profileProvider, model } },
        project(),
      ),
      { provider: expectedProvider, model, baseUrl: expectedBaseUrl },
      profileProvider,
    )
  }
})

test('keeps explicit Story overrides independent from the global profile', () => {
  assert.deepEqual(
    resolveStoryWritingProvider(
      { text: { provider: 'deepseek', model: 'ignored-global-model' } },
      project(false, {
        writingProvider: 'openai-compatible',
        writingModel: 'story-model',
        writingBaseUrl: 'https://story.example/v1',
      }),
    ),
    { provider: 'openai-compatible', model: 'story-model', baseUrl: 'https://story.example/v1' },
  )
})
