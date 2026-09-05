import assert from 'node:assert/strict'
import test from 'node:test'
import { ArchitectureGraphValidationError, parseArchitectureGraph } from '../src/features/architecture/architectureSchema.ts'

function graph(overrides: Record<string, unknown> = {}) {
  return {
    nodes: [
      { id: 'ui.story', layer: 'ui', label: 'Story Lab', detail: 'StoryLabPanel.tsx', evidence: [{ file: 'ui/src/features/stories/StoryLabPanel.tsx', line: 12 }] },
      { id: 'api.director', layer: 'api', label: 'Director API', detail: 'director.ts', evidence: [{ file: 'ui/src/api/director.ts', line: 20, column: 4 }] },
    ],
    edges: [{ source: 'ui.story', target: 'api.director', kind: 'http', label: 'POST', weight: 2, evidence: [{ file: 'ui/src/api/director.ts', line: 22 }] }],
    meta: {
      schema_version: 1,
      scope: 'Story Lab → Director',
      source_commit: '0123456789abcdef0123456789abcdef01234567',
      dirty: false,
      source_hash: 'abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789',
      generated_by: 'scripts/graphs/story_director_audio_flow.py',
      limitations: [],
      warnings: [],
    },
    ...overrides,
  }
}

test('validates the v1 architecture graph and preserves evidence', () => {
  const parsed = parseArchitectureGraph(graph())
  assert.equal(parsed.nodes.length, 2)
  assert.equal(parsed.edges[0].evidence[0].line, 22)
  assert.equal(parsed.meta.source_commit?.length, 40)
})

test('allows zero-weight reference edges without presenting them as executions', () => {
  const parsed = parseArchitectureGraph({
    ...graph(),
    edges: [{ ...graph().edges[0], weight: 0, kind: 'reference' }],
  })
  assert.equal(parsed.edges[0].weight, 0)
})

test('rejects malformed, duplicate and dangling graph data', () => {
  assert.throws(() => parseArchitectureGraph({}), ArchitectureGraphValidationError)
  const duplicate = graph({ nodes: [graph().nodes[0], graph().nodes[0]] })
  assert.throws(() => parseArchitectureGraph(duplicate), /duplicate node id/)
  const dangling = graph({ edges: [{ ...graph().edges[0], target: 'missing' }] })
  assert.throws(() => parseArchitectureGraph(dangling), /unknown node/)
})

test('rejects traversal, absolute and unsafe evidence paths', () => {
  for (const file of ['../secrets.txt', '/etc/passwd', 'ui/src/../secret.ts', 'ui/src/<img>.tsx', 'ui/src/file.ts#L1']) {
    const value = graph({
      nodes: [{ ...graph().nodes[0], evidence: [{ file, line: 1 }] }, graph().nodes[1]],
    })
    assert.throws(() => parseArchitectureGraph(value), /safe relative repository path/, file)
  }
})
