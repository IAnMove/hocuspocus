import { stableSerialize as sharedStableSerialize } from './agentContract'

/**
 * Shared command-plane states. `prepared` and `running` remain internal
 * execution states in agentContract; this is the transport-level vocabulary
 * exposed to the UI/API.
 */
export const COMMAND_STATUSES = [
  'completed',
  'queued',
  'awaiting_input',
  'partial',
  'failed',
] as const

export type CommandStatus = typeof COMMAND_STATUSES[number]
export type CommandResultStatus = CommandStatus
export type CommandActor = 'user' | 'wizard'
export type ArtifactKind = 'image' | 'audio' | 'video' | 'scene' | 'document'
export type PresentationSpeed = 'instant' | 'normal' | 'theatrical'

export const ARTIFACT_KINDS = ['image', 'audio', 'video', 'scene', 'document'] as const
export const PRESENTATION_SPEEDS = ['instant', 'normal', 'theatrical'] as const

export interface EntityRef {
  kind: string
  id: string
  workspaceId: string
  version?: number
}

export interface ArtifactRef {
  id: string
  kind: ArtifactKind
  owner: EntityRef
  taskId?: string
  uri: string
  metadata: Record<string, unknown>
}

/** Logical destination used by navigation and by the presentation layer. */
export interface NavigationTarget {
  destination: string
  section?: string
  entity?: EntityRef
  anchor?: string
}

/**
 * The smallest UI-facing plan: where to go and which semantic anchors to
 * reveal/focus. It deliberately contains no DOM selector or business state.
 * `replay` keeps a compatibility bridge with CapabilityPresentation while
 * presentation choreography is still being migrated.
 */
export interface PresentationPlan {
  navigationTarget?: NavigationTarget
  anchors: string[]
  focus?: string
  speed: PresentationSpeed
  replay?: 'atomic'
}

export interface StructuredError {
  code: string
  message: string
  retryable: boolean
  field?: string
  details?: Record<string, unknown>
}

export interface CommandEnvelope<T> {
  commandId: string
  capability: string
  workspaceId: string
  actor: CommandActor
  target?: EntityRef
  input: T
  idempotencyKey: string
  expectedVersion?: number
  presentation?: PresentationPlan
}

export interface CommandResult {
  commandId: string
  status: CommandStatus
  entities: EntityRef[]
  artifacts: ArtifactRef[]
  taskIds: string[]
  pipelineIds: string[]
  navigationTarget?: NavigationTarget
  error?: StructuredError
}

export interface CommandEnvelopeInput<T> {
  commandId: string
  capability: string
  workspaceId: string
  actor: CommandActor
  target?: EntityRef
  input: T
  idempotencyKey?: string
  expectedVersion?: number
  presentation?: PresentationPlan
}

export class CommandContractError extends Error {
  readonly code: string
  readonly path?: string

  constructor(message: string, code = 'invalid_command_contract', path?: string) {
    super(message)
    this.name = 'CommandContractError'
    this.code = code
    this.path = path
  }
}

type RecordValue = Record<string, unknown>

/**
 * Command payloads cross the UI/API boundary as JSON. Keeping that invariant
 * here prevents two especially subtle bugs: an idempotency key that changes
 * after a caller mutates its input object, and values (Date/Map/functions,
 * cycles, NaN, etc.) that the transport cannot faithfully reproduce.
 */
const MAX_JSON_DEPTH = 64


function isRecord(value: unknown): value is RecordValue {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}

function record(value: unknown, name: string): RecordValue {
  if (!isRecord(value)) throw new CommandContractError(`${name} debe ser un objeto.`, 'invalid_object', name)
  return value
}

function text(value: unknown, name: string): string {
  if (typeof value !== 'string' || !value.trim()) {
    throw new CommandContractError(`${name} no puede estar vacío.`, 'empty_id', name)
  }
  return value.trim()
}

function optionalText(value: unknown, name: string): string | undefined {
  if (value == null) return undefined
  return text(value, name)
}

function nonNegativeInteger(value: unknown, name: string): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) {
    throw new CommandContractError(`${name} debe ser un entero no negativo.`, 'invalid_version', name)
  }
  return value
}

function defineEnumerableValue(target: RecordValue, key: string, value: unknown): void {
  // `Object.defineProperty` keeps a JSON key named `__proto__` data-only and
  // avoids accidentally changing the prototype of the normalized object.
  Object.defineProperty(target, key, {
    configurable: true,
    enumerable: true,
    value,
    writable: true,
  })
}

function normalizeJsonValue(
  value: unknown,
  name: string,
  seen = new WeakSet<object>(),
  depth = 0,
): unknown {
  if (value === undefined) return undefined
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) {
      throw new CommandContractError(`${name} debe contener números finitos.`, 'invalid_json_value', name)
    }
    return value
  }
  if (typeof value !== 'object') {
    throw new CommandContractError(`${name} contiene un valor no serializable.`, 'invalid_json_value', name)
  }
  if (depth >= MAX_JSON_DEPTH) {
    throw new CommandContractError(`${name} es demasiado profundo.`, 'json_depth_exceeded', name)
  }
  if (seen.has(value)) {
    throw new CommandContractError(`${name} contiene una referencia circular.`, 'circular_json_value', name)
  }
    seen.add(value)
  try {
    if (Array.isArray(value)) {
      const normalizedArray: unknown[] = []
      for (let index = 0; index < value.length; index += 1) {
        const item = value[index]
        const normalized = normalizeJsonValue(item, `${name}[${index}]`, seen, depth + 1)
        // JSON.stringify serializes undefined array slots as null. Make that
        // conversion explicit so the object used for the command is stable.
        normalizedArray.push(normalized === undefined ? null : normalized)
      }
      return normalizedArray
    }
    if (!isRecord(value)) {
      throw new CommandContractError(`${name} debe ser JSON plano.`, 'invalid_json_value', name)
    }
    if (Object.getOwnPropertySymbols(value).length > 0) {
      throw new CommandContractError(`${name} no puede contener claves Symbol.`, 'invalid_json_value', name)
    }
    const normalized: RecordValue = {}
    for (const [key, item] of Object.entries(value)) {
      const child = normalizeJsonValue(item, `${name}.${key}`, seen, depth + 1)
      // Undefined object properties are omitted by the shared serializer. Do
      // the same in the cloned payload so both representations agree.
      if (child !== undefined) defineEnumerableValue(normalized, key, child)
    }
    return normalized
  } finally {
    seen.delete(value)
  }
}

function normalizePayload<T>(value: unknown, name: string, defaultValue: T): T {
  const normalized = normalizeJsonValue(value === undefined ? defaultValue : value, name)
  return normalized as T
}

function normalizeMetadata(value: unknown, name: string): RecordValue {
  const normalized = normalizeJsonValue(value, name)
  if (!isRecord(normalized)) {
    throw new CommandContractError(`${name} debe ser un objeto JSON.`, 'invalid_object', name)
  }
  return normalized
}

function stringList(value: unknown, name: string): string[] {
  if (value == null) return []
  if (!Array.isArray(value)) throw new CommandContractError(`${name} debe ser una lista.`, 'invalid_list', name)
  const seen = new Set<string>()
  return value.map((item, index) => {
    const next = text(item, `${name}[${index}]`)
    if (seen.has(next)) return next
    seen.add(next)
    return next
  })
}

function normalizedUniqueList(value: unknown, name: string): string[] {
  const values = stringList(value, name)
  return [...new Set(values)]
}

function expectedWorkspace(value: unknown, name = 'workspaceId'): string {
  return text(value, name)
}

function assertWorkspaceMatch(expected: string, actual: string, path: string): void {
  if (expected !== actual) {
    throw new CommandContractError(
      `${path} pertenece al workspace “${actual}”, no al workspace “${expected}”.`,
      'cross_workspace_reference',
      path,
    )
  }
}

function normalizeEntityRefRecord(raw: RecordValue, workspaceId?: string, path = 'entity'): EntityRef {
  const kind = text(raw.kind, `${path}.kind`)
  const id = text(raw.id, `${path}.id`)
  const refWorkspace = expectedWorkspace(raw.workspaceId, `${path}.workspaceId`)
  if (workspaceId !== undefined) assertWorkspaceMatch(expectedWorkspace(workspaceId), refWorkspace, `${path}.workspaceId`)
  const version = raw.version == null ? undefined : nonNegativeInteger(raw.version, `${path}.version`)
  return { kind, id, workspaceId: refWorkspace, ...(version == null ? {} : { version }) }
}

/** Normalize an entity reference and reject empty or cross-workspace IDs. */
export function normalizeEntityRef(value: unknown, workspaceId?: string): EntityRef {
  return normalizeEntityRefRecord(record(value, 'entity'), workspaceId)
}

export function assertEntityRef(value: unknown, workspaceId?: string): EntityRef {
  return normalizeEntityRef(value, workspaceId)
}

export function validateEntityRef(value: unknown, workspaceId?: string): string[] {
  try {
    normalizeEntityRef(value, workspaceId)
    return []
  } catch (error) {
    return [error instanceof Error ? error.message : 'Referencia de entidad inválida.']
  }
}

function normalizeArtifactRefRecord(raw: RecordValue, workspaceId?: string, path = 'artifact'): ArtifactRef {
  const id = text(raw.id, `${path}.id`)
  const kind = text(raw.kind, `${path}.kind`)
  if (!(ARTIFACT_KINDS as readonly string[]).includes(kind)) {
    throw new CommandContractError(`${path}.kind no es un tipo de artefacto válido.`, 'invalid_artifact_kind', `${path}.kind`)
  }
  const owner = normalizeEntityRefRecord(record(raw.owner, `${path}.owner`), workspaceId, `${path}.owner`)
  const taskId = optionalText(raw.taskId, `${path}.taskId`)
  const uri = text(raw.uri, `${path}.uri`)
  const metadata = raw.metadata == null ? {} : normalizeMetadata(raw.metadata, `${path}.metadata`)
  return {
    id,
    kind: kind as ArtifactKind,
    owner,
    ...(taskId == null ? {} : { taskId }),
    uri,
    metadata,
  }
}

/** Normalize an artifact and bind its owner to the expected workspace. */
export function normalizeArtifactRef(value: unknown, workspaceId?: string): ArtifactRef {
  return normalizeArtifactRefRecord(record(value, 'artifact'), workspaceId)
}

export function assertArtifactRef(value: unknown, workspaceId?: string): ArtifactRef {
  return normalizeArtifactRef(value, workspaceId)
}

export function validateArtifactRef(value: unknown, workspaceId?: string): string[] {
  try {
    normalizeArtifactRef(value, workspaceId)
    return []
  } catch (error) {
    return [error instanceof Error ? error.message : 'Referencia de artefacto inválida.']
  }
}

function normalizeNavigationTargetRecord(raw: RecordValue, workspaceId?: string, path = 'navigationTarget'): NavigationTarget {
  const destination = text(raw.destination ?? raw.tab ?? raw.area, `${path}.destination`)
  const section = optionalText(raw.section, `${path}.section`)
  const anchor = optionalText(raw.anchor, `${path}.anchor`)
  const rawEntity = raw.entity ?? raw.target
  const entity = rawEntity == null ? undefined : normalizeEntityRefRecord(record(rawEntity, `${path}.entity`), workspaceId, `${path}.entity`)
  return {
    destination,
    ...(section == null ? {} : { section }),
    ...(entity == null ? {} : { entity }),
    ...(anchor == null ? {} : { anchor }),
  }
}

export function normalizeNavigationTarget(value: unknown, workspaceId?: string): NavigationTarget {
  return normalizeNavigationTargetRecord(record(value, 'navigationTarget'), workspaceId)
}

export function assertNavigationTarget(value: unknown, workspaceId?: string): NavigationTarget {
  return normalizeNavigationTarget(value, workspaceId)
}

export function validateNavigationTarget(value: unknown, workspaceId?: string): string[] {
  try {
    normalizeNavigationTarget(value, workspaceId)
    return []
  } catch (error) {
    return [error instanceof Error ? error.message : 'Destino de navegación inválido.']
  }
}

function normalizePresentationRecord(raw: RecordValue, workspaceId?: string): PresentationPlan {
  const rawNavigation = raw.navigationTarget ?? raw.navigation
  const navigationTarget = rawNavigation == null
    ? (raw.destination == null ? undefined : normalizeNavigationTargetRecord({
      destination: raw.destination,
      section: raw.section,
      anchor: raw.anchor,
    }, workspaceId, 'presentation.navigationTarget'))
    : normalizeNavigationTargetRecord(record(rawNavigation, 'presentation.navigationTarget'), workspaceId, 'presentation.navigationTarget')
  const anchors = normalizedUniqueList(raw.anchors, 'presentation.anchors')
  const focus = optionalText(raw.focus, 'presentation.focus')
  const speed = raw.speed == null ? 'normal' : text(raw.speed, 'presentation.speed')
  if (!(PRESENTATION_SPEEDS as readonly string[]).includes(speed)) {
    throw new CommandContractError('presentation.speed no es válido.', 'invalid_presentation_speed', 'presentation.speed')
  }
  if (raw.replay != null && raw.replay !== 'atomic') {
    throw new CommandContractError('presentation.replay sólo admite “atomic”.', 'invalid_presentation_replay', 'presentation.replay')
  }
  return {
    ...(navigationTarget == null ? {} : { navigationTarget }),
    anchors,
    ...(focus == null ? {} : { focus }),
    speed: speed as PresentationSpeed,
    ...(raw.replay == null ? {} : { replay: 'atomic' }),
  }
}

export function normalizePresentationPlan(value: unknown, workspaceId?: string): PresentationPlan {
  return normalizePresentationRecord(record(value, 'presentation'), workspaceId)
}

export function assertPresentationPlan(value: unknown, workspaceId?: string): PresentationPlan {
  return normalizePresentationPlan(value, workspaceId)
}

export function validatePresentationPlan(value: unknown, workspaceId?: string): string[] {
  try {
    normalizePresentationPlan(value, workspaceId)
    return []
  } catch (error) {
    return [error instanceof Error ? error.message : 'Plan de presentación inválido.']
  }
}

/**
 * Compatibility bridge for the currently registered capability metadata.
 * It keeps destination/anchors/replay usable while callers migrate to the
 * global command contract.
 */
export function presentationPlanFromCapabilityPresentation(value: {
  destination: string
  anchors?: string[]
  replay?: 'atomic'
}): PresentationPlan {
  return normalizePresentationPlan(value)
}

export function normalizeStructuredError(value: unknown): StructuredError {
  if (typeof value === 'string') {
    return { code: 'unknown_error', message: text(value, 'error.message'), retryable: false }
  }
  const raw = record(value, 'error')
  const code = text(raw.code, 'error.code')
  const message = text(raw.message, 'error.message')
  const retryable = raw.retryable == null
    ? false
    : (typeof raw.retryable === 'boolean'
      ? raw.retryable
      : (() => {
        throw new CommandContractError('error.retryable debe ser booleano.', 'invalid_boolean', 'error.retryable')
      })())
  const field = optionalText(raw.field, 'error.field')
  const details = raw.details == null ? undefined : normalizeMetadata(raw.details, 'error.details')
  return {
    code,
    message,
    retryable,
    ...(field == null ? {} : { field }),
    ...(details == null ? {} : { details }),
  }
}

export function assertStructuredError(value: unknown): StructuredError {
  return normalizeStructuredError(value)
}

export function validateStructuredError(value: unknown): string[] {
  try {
    normalizeStructuredError(value)
    return []
  } catch (error) {
    return [error instanceof Error ? error.message : 'Error estructurado inválido.']
  }
}

function normalizeExpectedVersion(value: unknown, name: string): number | undefined {
  return value == null ? undefined : nonNegativeInteger(value, name)
}

function targetForKey(target: EntityRef | undefined): Record<string, unknown> | null {
  return target == null ? null : {
    kind: target.kind,
    id: target.id,
    workspaceId: target.workspaceId,
    ...(target.version == null ? {} : { version: target.version }),
  }
}

export interface IdempotencyKeyInput<T> {
  workspaceId: string
  capability: string
  target?: EntityRef
  input: T
}

/**
 * Stable, inspectable key for command retries. The shared stable serializer
 * from agentContract sorts object keys recursively, so object insertion order
 * cannot produce a second command identity.
 */
export function buildIdempotencyKey<T>(value: IdempotencyKeyInput<T>): string {
  const raw = record(value, 'idempotency')
  const workspaceId = expectedWorkspace(raw.workspaceId, 'workspaceId')
  const capability = text(raw.capability, 'capability')
  const target = raw.target == null ? undefined : normalizeEntityRef(raw.target, workspaceId)
  const input = normalizePayload<T>(raw.input, 'input', {} as T)
  return `command:${sharedStableSerialize({
    workspaceId,
    capability,
    target: targetForKey(target),
    input,
  })}`
}

/** Named aliases make the constructor discoverable during the migration. */
export const commandIdempotencyKey = buildIdempotencyKey
export const idempotencyKey = buildIdempotencyKey
export const createIdempotencyKey = buildIdempotencyKey

export function createCommandEnvelope<T>(value: CommandEnvelopeInput<T>): CommandEnvelope<T> {
  const normalized = normalizeCommandEnvelope<T>(value)
  return normalized
}

export function normalizeCommandEnvelope<T>(value: unknown): CommandEnvelope<T> {
  const raw = record(value, 'command')
  const commandId = text(raw.commandId ?? raw.command_id, 'command.commandId')
  const capability = text(raw.capability, 'command.capability')
  const workspaceId = expectedWorkspace(raw.workspaceId ?? raw.workspace_id, 'command.workspaceId')
  const actor = text(raw.actor, 'command.actor')
  if (actor !== 'user' && actor !== 'wizard') {
    throw new CommandContractError('command.actor debe ser “user” o “wizard”.', 'invalid_actor', 'command.actor')
  }
  const target = raw.target == null ? undefined : normalizeEntityRef(raw.target, workspaceId)
  const input = normalizePayload<T>(raw.input, 'command.input', {} as T)
  const expectedVersion = normalizeExpectedVersion(raw.expectedVersion ?? raw.expected_version, 'command.expectedVersion')
  const presentation = raw.presentation == null ? undefined : normalizePresentationPlan(raw.presentation, workspaceId)
  const derivedKey = buildIdempotencyKey({ workspaceId, capability, target, input })
  const suppliedKey = raw.idempotencyKey ?? raw.idempotency_key
  if (suppliedKey != null && text(suppliedKey, 'command.idempotencyKey') !== derivedKey) {
    throw new CommandContractError(
      'command.idempotencyKey no coincide con workspace, capability, target e input.',
      'idempotency_key_mismatch',
      'command.idempotencyKey',
    )
  }
  return {
    commandId,
    capability,
    workspaceId,
    actor: actor as CommandActor,
    ...(target == null ? {} : { target }),
    input,
    idempotencyKey: derivedKey,
    ...(expectedVersion == null ? {} : { expectedVersion }),
    ...(presentation == null ? {} : { presentation }),
  }
}

export function assertCommandEnvelope<T>(value: unknown): CommandEnvelope<T> {
  return normalizeCommandEnvelope<T>(value)
}

export function validateCommandEnvelope(value: unknown): string[] {
  try {
    normalizeCommandEnvelope(value)
    return []
  } catch (error) {
    return [error instanceof Error ? error.message : 'Envelope de comando inválido.']
  }
}

function normalizeStatus(value: unknown): CommandStatus {
  const status = text(value, 'result.status')
  if (!(COMMAND_STATUSES as readonly string[]).includes(status)) {
    throw new CommandContractError(`result.status “${status}” no es válido.`, 'invalid_status', 'result.status')
  }
  return status as CommandStatus
}

export function normalizeCommandResult(value: unknown, workspaceId?: string): CommandResult {
  const raw = record(value, 'result')
  const expected = workspaceId == null ? undefined : expectedWorkspace(workspaceId)
  const commandId = text(raw.commandId ?? raw.command_id, 'result.commandId')
  const status = normalizeStatus(raw.status)
  const entities = raw.entities == null
    ? []
    : (Array.isArray(raw.entities)
      ? raw.entities.map((item, index) => normalizeEntityRefRecord(record(item, `result.entities[${index}]`), expected, `result.entities[${index}]`))
      : (() => { throw new CommandContractError('result.entities debe ser una lista.', 'invalid_list', 'result.entities') })())
  const artifacts = raw.artifacts == null
    ? []
    : (Array.isArray(raw.artifacts)
      ? raw.artifacts.map((item, index) => normalizeArtifactRefRecord(record(item, `result.artifacts[${index}]`), expected, `result.artifacts[${index}]`))
      : (() => { throw new CommandContractError('result.artifacts debe ser una lista.', 'invalid_list', 'result.artifacts') })())
  const workspaces = new Set([...entities.map(item => item.workspaceId), ...artifacts.map(item => item.owner.workspaceId)])
  if (expected == null && workspaces.size > 1) {
    throw new CommandContractError('result contiene referencias de varios workspaces.', 'cross_workspace_reference', 'result')
  }
  const inferredWorkspace = expected ?? [...workspaces][0]
  const taskIds = normalizedUniqueList(raw.taskIds ?? raw.task_ids, 'result.taskIds')
  const pipelineIds = normalizedUniqueList(raw.pipelineIds ?? raw.pipeline_ids, 'result.pipelineIds')
  const navigationTarget = raw.navigationTarget == null
    ? undefined
    : normalizeNavigationTarget(raw.navigationTarget, inferredWorkspace)
  const error = raw.error == null ? undefined : normalizeStructuredError(raw.error)
  return {
    commandId,
    status,
    entities,
    artifacts,
    taskIds,
    pipelineIds,
    ...(navigationTarget == null ? {} : { navigationTarget }),
    ...(error == null ? {} : { error }),
  }
}

export function assertCommandResult(value: unknown, workspaceId?: string): CommandResult {
  return normalizeCommandResult(value, workspaceId)
}

export function validateCommandResult(value: unknown, workspaceId?: string): string[] {
  try {
    normalizeCommandResult(value, workspaceId)
    return []
  } catch (error) {
    return [error instanceof Error ? error.message : 'Resultado de comando inválido.']
  }
}

/** Canonical JSON-like serialization for transport snapshots and tests. */
export function serializeCommand<T>(value: CommandEnvelope<T>): string {
  return sharedStableSerialize(normalizeCommandEnvelope<T>(value))
}

export function serializeCommandResult(value: CommandResult, workspaceId?: string): string {
  return sharedStableSerialize(normalizeCommandResult(value, workspaceId))
}

/** Explicit workspace guard for adapters before they consume a reference. */
export function assertWorkspaceScope(workspaceId: string, references: readonly (EntityRef | ArtifactRef)[]): void {
  const expected = expectedWorkspace(workspaceId)
  if (!Array.isArray(references)) {
    throw new CommandContractError('references debe ser una lista.', 'invalid_list', 'references')
  }
  references.forEach((reference, index) => {
    const path = `references[${index}]`
    const raw = record(reference, path)
    if ('owner' in raw) {
      normalizeArtifactRefRecord(raw, expected, path)
    } else {
      normalizeEntityRefRecord(raw, expected, path)
    }
  })
}

export function sameWorkspace(left: EntityRef | ArtifactRef, right: EntityRef | ArtifactRef): boolean {
  const normalizeReferenceWorkspace = (value: unknown, path: string): string => {
    const raw = record(value, path)
    return 'owner' in raw
      ? normalizeArtifactRefRecord(raw, undefined, path).owner.workspaceId
      : normalizeEntityRefRecord(raw, undefined, path).workspaceId
  }
  const leftWorkspace = normalizeReferenceWorkspace(left, 'left')
  const rightWorkspace = normalizeReferenceWorkspace(right, 'right')
  return leftWorkspace === rightWorkspace
}

/**
 * Re-export the shared canonical serializer through the command boundary, but
 * validate first. This keeps the key format compatible with agentContract
 * while rejecting values that JSON transport would silently corrupt.
 */
export function stableSerialize(value: unknown): string {
  return sharedStableSerialize(normalizeJsonValue(value, 'value'))
}
