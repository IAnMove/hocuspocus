import { asMap, firstStored, known, mapAt, mintId, redactedParams, storedString, text, UNKNOWN } from './fields'
import { parseRefList, REF_ROLES, resolveRef } from './refs'
import type {
  CanonicalRef, InspectContext, InspectedAttempt, InspectedModel, JsonMap,
  PromptChange, PromptTransformSource, StoredField,
} from './types'

const TRANSFORM_SOURCES: PromptTransformSource[] = ['guide', 'policy', 'provider']

function transformSource(value: unknown): PromptTransformSource {
  const token = (text(value) || '').toLowerCase()
  if (TRANSFORM_SOURCES.includes(token as PromptTransformSource)) return token as PromptTransformSource
  return 'unknown'
}

function storedFrom(value: unknown): StoredField<string> {
  if (value == null) return UNKNOWN
  return known(typeof value === 'string' ? value : String(value))
}

function parseChange(value: unknown): PromptChange | null {
  const raw = asMap(value)
  if (!raw.field && raw.before == null && raw.after == null && !raw.source) return null
  return {
    source: transformSource(raw.source || raw.kind || raw.op),
    field: text(raw.field) || 'prompt',
    before: storedFrom(raw.before ?? raw.original),
    after: storedFrom(raw.after ?? raw.effective),
  }
}

function changeList(value: unknown): PromptChange[] {
  if (!Array.isArray(value)) return []
  return value.map(parseChange).filter((item): item is PromptChange => item != null)
}

function readChanges(source: JsonMap, prompts: JsonMap, generation: JsonMap): PromptChange[] {
  const lists = [
    source.transforms, source.prompt_transforms, prompts.transforms,
    generation.transforms, mapAt(generation, ['prompts']).transforms,
  ]
  for (const list of lists) {
    const parsed = changeList(list)
    if (parsed.length) return parsed
  }
  return []
}

function impliedChange(original: StoredField<string>, effective: StoredField<string>): PromptChange[] {
  if (!original.known || !effective.known || original.value === effective.value) return []
  return [{ source: 'unknown', field: 'prompt', before: original, after: effective }]
}

function readOriginal(source: JsonMap, prompts: JsonMap): StoredField<string> {
  const labeled = firstStored(source, ['prompt_original'])
  if (labeled.known) return labeled
  const nested = firstStored(prompts, ['original', 'prompt_original'])
  if (nested.known) return nested
  if (source.source !== 'generation' && source.source !== 'manual') return UNKNOWN
  return storedString(source, 'prompt')
}

function readEffective(source: JsonMap, prompts: JsonMap): StoredField<string> {
  const labeled = firstStored(source, ['prompt_effective'])
  if (labeled.known) return labeled
  return firstStored(prompts, ['effective', 'prompt_effective'])
}

function readModel(block: JsonMap): InspectedModel {
  return {
    provider: storedString(block, 'provider'),
    id: firstStored(block, ['id', 'model_type', 'name']),
    version: firstStored(block, ['version', 'revision']),
  }
}

function modelBlock(source: JsonMap, generation: JsonMap): JsonMap {
  const model = asMap(source.model)
  return Object.keys(model).length ? model : asMap(generation.model)
}

function paramBlock(source: JsonMap, generation: JsonMap): JsonMap {
  const configuration = asMap(asMap(source.model).configuration)
  if (Object.keys(configuration).length) return configuration
  const parameters = asMap(generation.parameters)
  if (Object.keys(parameters).length) return parameters
  const params = asMap(source.params)
  if (Object.keys(params).length) return params
  return asMap(source.parameters)
}

function collectRefs(params: JsonMap, lineage: JsonMap, catalog: InspectContext['catalog']): CanonicalRef[] {
  const refs: CanonicalRef[] = []
  for (const role of REF_ROLES) refs.push(...parseRefList(role, params[role]))
  const inputs = Array.isArray(lineage.parents) ? lineage.parents : []
  for (const item of inputs) refs.push(...parseRefList(text(asMap(item).kind) || 'input', item))
  return refs.map(ref => resolveRef(ref, catalog || []))
}

function readIntent(source: JsonMap, provenance: JsonMap, correlations: JsonMap): StoredField<string> {
  const fromCorrelations = firstStored(correlations, ['command_id', 'intent_id'])
  if (fromCorrelations.known) return fromCorrelations
  const fromCommand = firstStored(asMap(provenance.command), ['command_id'])
  if (fromCommand.known) return fromCommand
  const fromMeta = firstStored(asMap(source.metadata), ['intent_id', 'command_id'])
  if (fromMeta.known) return fromMeta
  return firstStored(source, ['intent_id', 'command_id'])
}

function folderOf(source: JsonMap, origin: JsonMap, workspace: string): string {
  return text(source.output_folder)
    || text(origin.output_folder)
    || text(source.outputFolder)
    || text(source.workspace)
    || workspace
    || 'default'
}

function readNegative(source: JsonMap, params: JsonMap): StoredField<string> {
  const labeled = firstStored(source, ['negative_prompt', 'negativePrompt'])
  if (labeled.known) return labeled
  return storedString(params, 'negative_prompt')
}

export function belongsToFolder(attempt: InspectedAttempt, folder: string): boolean {
  return Boolean(folder) && attempt.outputFolder === folder
}

export function inspectAttempt(source: unknown, context: InspectContext): InspectedAttempt {
  const raw = asMap(source)
  const origin = asMap(raw.origin)
  const generation = asMap(raw.generation)
  const promptMap = asMap(raw.prompts)
  const prompts = Object.keys(promptMap).length ? promptMap : mapAt(generation, ['prompts'])
  const originalPrompt = readOriginal(raw, prompts)
  const effectivePrompt = readEffective(raw, prompts)
  const changes = readChanges(raw, prompts, generation)
  const params = redactedParams(paramBlock(raw, generation))
  const lineage = asMap(raw.lineage)
  const outputFolder = folderOf(raw, origin, context.workspace)
  return {
    attemptId: text(raw.generation_id) || text(raw.id) || mintId('attempt'),
    generationId: text(raw.generation_id) || text(mapAt(raw, ['technical']).generation_id),
    intentId: readIntent(raw, asMap(raw.provenance), asMap(raw.correlations)),
    outputFolder,
    workspaceId: text(raw.workspace_id) || text(origin.workspace_id),
    originalPrompt,
    effectivePrompt,
    negativePrompt: readNegative(raw, params),
    changes: changes.length ? changes : impliedChange(originalPrompt, effectivePrompt),
    model: readModel(modelBlock(raw, generation)),
    params,
    refs: collectRefs(params, lineage, context.catalog),
    product: text(raw.product) || text(origin.tool),
    status: text(raw.status),
    createdAt: text(raw.createdAt) || text(mapAt(raw, ['timestamps']).created_at),
    mode: text(raw.mode) || text(params.generation_mode),
  }
}
