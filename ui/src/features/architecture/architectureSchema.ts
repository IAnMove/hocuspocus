export type ArchitectureEvidence = {
  file: string
  line: number
  column?: number
}

export type ArchitectureNode = {
  id: string
  layer: string
  label: string
  detail: string
  evidence: ArchitectureEvidence[]
}

export type ArchitectureEdge = {
  source: string
  target: string
  kind: string
  label: string
  weight: number
  evidence: ArchitectureEvidence[]
  highlight?: boolean
}

export type ArchitectureMeta = {
  schema_version: 1
  scope: string
  source_commit: string | null
  dirty: boolean
  source_hash: string
  generated_by: string
  limitations: string[]
  warnings: string[]
}

export type ArchitectureGraph = {
  nodes: ArchitectureNode[]
  edges: ArchitectureEdge[]
  meta: ArchitectureMeta
}

const MAX_NODES = 2_000
const MAX_EDGES = 8_000
const MAX_EVIDENCE_PER_ITEM = 32
const MAX_TEXT = 4_000
const MAX_PATH = 240

export class ArchitectureGraphValidationError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ArchitectureGraphValidationError'
  }
}

function fail(message: string): never {
  throw new ArchitectureGraphValidationError(message)
}

function record(value: unknown, name: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    fail(`${name} must be an object`)
  }
  return value as Record<string, unknown>
}

function boundedString(value: unknown, name: string, max = MAX_TEXT): string {
  const hasControlCharacter = typeof value === 'string'
    && [...value].some(character => character.charCodeAt(0) <= 31 || character.charCodeAt(0) === 127)
  if (typeof value !== 'string' || value.length === 0 || value.length > max || hasControlCharacter) {
    fail(`${name} must be a non-empty safe string`)
  }
  return value
}

function textString(value: unknown, name: string, max = MAX_TEXT): string {
  const hasControlCharacter = typeof value === 'string'
    && [...value].some(character => character.charCodeAt(0) <= 31 || character.charCodeAt(0) === 127)
  if (typeof value !== 'string' || value.length > max || hasControlCharacter) {
    fail(`${name} must be a safe string`)
  }
  return value
}

function array(value: unknown, name: string, max: number): unknown[] {
  if (!Array.isArray(value) || value.length > max) fail(`${name} must be an array with at most ${max} items`)
  return value
}

function integer(value: unknown, name: string, min: number, max: number): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < min || value > max) {
    fail(`${name} must be an integer between ${min} and ${max}`)
  }
  return value
}

function safeRelativePath(value: unknown, name: string): string {
  const file = boundedString(value, name, MAX_PATH)
  const segments = file.split('/')
  if (
    file.startsWith('/')
    || file.includes('\\')
    || file.includes('//')
    || file.includes('?')
    || file.includes('#')
    || segments.some(segment => segment === '' || segment === '.' || segment === '..')
    || segments.some(segment => !/^[A-Za-z0-9._@+()\- ]+$/.test(segment))
  ) {
    fail(`${name} must be a safe relative repository path`)
  }
  return file
}

function parseEvidence(value: unknown, name: string): ArchitectureEvidence[] {
  return array(value, name, MAX_EVIDENCE_PER_ITEM).map((entry, index) => {
    const item = record(entry, `${name}[${index}]`)
    const evidence: ArchitectureEvidence = {
      file: safeRelativePath(item.file, `${name}[${index}].file`),
      line: integer(item.line, `${name}[${index}].line`, 1, 1_000_000),
    }
    if (item.column !== undefined) {
      evidence.column = integer(item.column, `${name}[${index}].column`, 1, 1_000_000)
    }
    return evidence
  })
}

function parseNode(value: unknown, index: number): ArchitectureNode {
  const item = record(value, `nodes[${index}]`)
  return {
    id: boundedString(item.id, `nodes[${index}].id`, 200),
    layer: boundedString(item.layer, `nodes[${index}].layer`, 100),
    label: boundedString(item.label, `nodes[${index}].label`),
    detail: boundedString(item.detail, `nodes[${index}].detail`),
    evidence: parseEvidence(item.evidence, `nodes[${index}].evidence`),
  }
}

function parseEdge(value: unknown, index: number): ArchitectureEdge {
  const item = record(value, `edges[${index}]`)
  const edge: ArchitectureEdge = {
    source: boundedString(item.source, `edges[${index}].source`, 200),
    target: boundedString(item.target, `edges[${index}].target`, 200),
    kind: boundedString(item.kind, `edges[${index}].kind`, 100),
    label: textString(item.label, `edges[${index}].label`),
    // A zero weight is a deliberate marker for a static reference/read/write
    // edge. It must not be presented as an execution count by the viewer.
    weight: integer(item.weight, `edges[${index}].weight`, 0, 1_000),
    evidence: parseEvidence(item.evidence, `edges[${index}].evidence`),
  }
  if (item.highlight !== undefined) {
    if (typeof item.highlight !== 'boolean') fail(`edges[${index}].highlight must be a boolean`)
    edge.highlight = item.highlight
  }
  return edge
}

function parseMeta(value: unknown): ArchitectureMeta {
  const item = record(value, 'meta')
  if (item.schema_version !== 1) fail('meta.schema_version must be 1')
  const sourceCommit = item.source_commit
  if (sourceCommit !== null && (typeof sourceCommit !== 'string' || !/^[0-9a-f]{40}$/i.test(sourceCommit))) {
    fail('meta.source_commit must be null or a 40-character commit SHA')
  }
  const limitations = array(item.limitations, 'meta.limitations', 100).map((entry, index) => boundedString(entry, `meta.limitations[${index}]`))
  const warnings = array(item.warnings, 'meta.warnings', 100).map((entry, index) => boundedString(entry, `meta.warnings[${index}]`))
  return {
    schema_version: 1,
    scope: boundedString(item.scope, 'meta.scope', 500),
    source_commit: sourceCommit,
    dirty: typeof item.dirty === 'boolean' ? item.dirty : fail('meta.dirty must be a boolean'),
    source_hash: (() => {
      const sourceHash = boundedString(item.source_hash, 'meta.source_hash', 64)
      if (!/^[0-9a-f]{64}$/i.test(sourceHash)) fail('meta.source_hash must be a 64-character SHA-256 hash')
      return sourceHash
    })(),
    generated_by: boundedString(item.generated_by, 'meta.generated_by', 200),
    limitations,
    warnings,
  }
}

export function parseArchitectureGraph(value: unknown): ArchitectureGraph {
  const root = record(value, 'architecture graph')
  const nodes = array(root.nodes, 'nodes', MAX_NODES).map(parseNode)
  const edges = array(root.edges, 'edges', MAX_EDGES).map(parseEdge)
  const ids = new Set<string>()
  for (const node of nodes) {
    if (ids.has(node.id)) fail(`duplicate node id: ${node.id}`)
    ids.add(node.id)
  }
  for (const edge of edges) {
    if (!ids.has(edge.source) || !ids.has(edge.target)) {
      fail(`edge references an unknown node: ${edge.source} -> ${edge.target}`)
    }
  }
  return { nodes, edges, meta: parseMeta(root.meta) }
}
