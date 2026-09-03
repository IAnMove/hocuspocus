import {
  fetchWizardConversation,
  saveWizardConversation,
  WizardConversationRequestError,
  type WizardConversationPayload,
} from '../../api/wizard'
import {
  mergeWizardMessages,
  normalizeRemoteWizardMessages,
} from './wizardConversationSync'

export interface WizardConversationTransport {
  fetch: (workspace: string) => Promise<WizardConversationPayload>
  save: (workspace: string, conversation: WizardConversationPayload) => Promise<WizardConversationPayload>
}

export interface WizardConversationSaveResult {
  conversation: WizardConversationPayload
  merged: boolean
}

export type WizardConversationSnapshotStore = Map<string, WizardConversationPayload>

export interface QueuedWizardConversationWrite {
  workspace: string
  captured: WizardConversationPayload
  base?: WizardConversationPayload
}

export function resolveWizardConversationHydration(
  known: WizardConversationPayload | undefined,
  incoming: WizardConversationPayload,
): { snapshot: WizardConversationPayload; applyToVisibleState: boolean } {
  if (known && known.revision >= incoming.revision) {
    return { snapshot: known, applyToVisibleState: false }
  }
  return { snapshot: incoming, applyToVisibleState: true }
}

/**
 * Rebase browser-visible edits over a hydration response that lost a race to
 * a confirmed save. The stale response is the three-way base, so confirmed
 * turns added after it are retained while local edits still win. Missing
 * browser-cache values are not treated as deletes unless the caller records
 * an explicit user clear.
 */
export function rebaseStaleWizardConversationHydration(
  visible: WizardConversationPayload,
  stale: WizardConversationPayload,
  confirmed: WizardConversationPayload,
  options: { honorLocalDeletes?: boolean } = {},
): { conversation: WizardConversationPayload; needsPersist: boolean } {
  const honorLocalDeletes = options.honorLocalDeletes ?? false
  const conversation: WizardConversationPayload = {
    version: 1,
    revision: confirmed.revision,
    messages: mergeQueuedValues(visible.messages, stale.messages, confirmed.messages, honorLocalDeletes),
    executions: mergeQueuedValues(visible.executions, stale.executions, confirmed.executions, honorLocalDeletes),
    requestedActions: mergeQueuedValues(
      visible.requestedActions,
      stale.requestedActions,
      confirmed.requestedActions,
      honorLocalDeletes,
    ),
    executedActions: mergeQueuedValues(
      visible.executedActions,
      stale.executedActions,
      confirmed.executedActions,
      honorLocalDeletes,
    ),
    confirmations: mergeQueuedValues(
      visible.confirmations,
      stale.confirmations,
      confirmed.confirmations,
      honorLocalDeletes,
    ),
  }
  const semanticContent = (value: WizardConversationPayload) => ({
    messages: value.messages,
    executions: value.executions,
    requestedActions: value.requestedActions ?? [],
    executedActions: value.executedActions ?? [],
    confirmations: value.confirmations ?? [],
  })
  return {
    conversation,
    needsPersist: stableKey(semanticContent(conversation)) !== stableKey(semanticContent(confirmed)),
  }
}

const defaultTransport: WizardConversationTransport = {
  fetch: fetchWizardConversation,
  save: saveWizardConversation,
}

function isEmptyStableValue(value: unknown): boolean {
  return value == null || value === '' || (Array.isArray(value) && value.length === 0)
}

function stableKey(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value) ?? String(value)
  if (Array.isArray(value)) return `[${value.map(stableKey).join(',')}]`
  const record = value as Record<string, unknown>
  return `{${Object.keys(record)
    .sort()
    .filter(key => !isEmptyStableValue(record[key]))
    .map(key => `${JSON.stringify(key)}:${stableKey(record[key])}`)
    .join(',')}}`
}

function mergeUniqueValues(remote: unknown, local: unknown): unknown[] {
  const merged: unknown[] = []
  const seen = new Set<string>()
  for (const value of [
    ...(Array.isArray(remote) ? remote : []),
    ...(Array.isArray(local) ? local : []),
  ]) {
    const key = stableKey(value)
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(value)
  }
  return merged.slice(-80)
}

function valueIdentity(value: unknown): string {
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>
    if (typeof record.id === 'string' && record.id) return `id:${record.id}`
    if (typeof record.executionKey === 'string' && record.executionKey) return `execution:${record.executionKey}`
  }
  return `value:${stableKey(value)}`
}

/** Apply local edits/deletes since base without discarding concurrent values. */
function mergeQueuedValues(
  local: unknown,
  base: unknown,
  canonical: unknown,
  honorLocalDeletes = true,
): unknown[] {
  const localValues = Array.isArray(local) ? local : []
  const baseValues = Array.isArray(base) ? base : []
  const canonicalValues = Array.isArray(canonical) ? canonical : []
  const localById = new Map(localValues.map(value => [valueIdentity(value), value]))
  const baseById = new Map(baseValues.map(value => [valueIdentity(value), value]))
  const merged: unknown[] = []
  const seen = new Set<string>()

  canonicalValues.forEach(value => {
    const id = valueIdentity(value)
    const baseValue = baseById.get(id)
    const localValue = localById.get(id)
    if (honorLocalDeletes && baseById.has(id) && !localById.has(id)) return
    if (localById.has(id) && (!baseById.has(id) || stableKey(localValue) !== stableKey(baseValue))) {
      merged.push(localValue)
    } else {
      merged.push(value)
    }
    seen.add(id)
  })
  localValues.forEach(value => {
    const id = valueIdentity(value)
    if (seen.has(id)) return
    merged.push(value)
    seen.add(id)
  })
  return merged.slice(-80)
}

export function mergeQueuedWizardConversationSnapshots(
  local: WizardConversationPayload,
  base: WizardConversationPayload | undefined,
  canonical: WizardConversationPayload,
): WizardConversationPayload {
  return {
    version: 1,
    revision: canonical.revision,
    messages: mergeQueuedValues(local.messages, base?.messages, canonical.messages),
    executions: mergeQueuedValues(local.executions, base?.executions, canonical.executions),
    requestedActions: local.requestedActions === undefined
      ? canonical.requestedActions
      : mergeQueuedValues(local.requestedActions, base?.requestedActions, canonical.requestedActions),
    executedActions: local.executedActions === undefined
      ? canonical.executedActions
      : mergeQueuedValues(local.executedActions, base?.executedActions, canonical.executedActions),
    confirmations: local.confirmations === undefined
      ? canonical.confirmations
      : mergeQueuedValues(local.confirmations, base?.confirmations, canonical.confirmations),
  }
}

/**
 * Build the one payload used after a CAS conflict.
 *
 * The server snapshot is canonical. Existing ids remain in server order and
 * local-only turn ids are appended once, so repeating the merge is harmless.
 */
export function mergeWizardConversationSnapshots(
  local: WizardConversationPayload,
  remote: WizardConversationPayload,
): WizardConversationPayload {
  const remoteMessages = normalizeRemoteWizardMessages(remote.messages, remote.executions)
  const localMessages = normalizeRemoteWizardMessages(local.messages, local.executions)
  return {
    version: 1,
    revision: remote.revision,
    messages: mergeWizardMessages(localMessages, remoteMessages),
    executions: mergeUniqueValues(remote.executions, local.executions),
    requestedActions: mergeUniqueValues(remote.requestedActions, local.requestedActions),
    executedActions: mergeUniqueValues(remote.executedActions, local.executedActions),
    confirmations: mergeUniqueValues(remote.confirmations, local.confirmations),
  }
}

export function isWizardConversationConflict(error: unknown): boolean {
  if (error instanceof WizardConversationRequestError) return error.status === 409
  return Boolean(
    error
    && typeof error === 'object'
    && (error as { status?: unknown }).status === 409,
  )
}

/**
 * Save a Wizard conversation, recovering one and only one CAS conflict.
 *
 * A validation, auth or server error is propagated immediately. If the
 * retry conflicts again, that second error is propagated to the caller rather
 * than starting an unbounded refetch/save loop.
 */
export async function saveWizardConversationWithRecovery(
  workspace: string,
  conversation: WizardConversationPayload,
  transport: WizardConversationTransport = defaultTransport,
  base?: WizardConversationPayload,
): Promise<WizardConversationSaveResult> {
  try {
    return {
      conversation: await transport.save(workspace, conversation),
      merged: false,
    }
  } catch (error) {
    if (!isWizardConversationConflict(error)) throw error
    const remote = await transport.fetch(workspace)
    const merged = base
      ? mergeQueuedWizardConversationSnapshots(conversation, base, remote)
      : mergeWizardConversationSnapshots(conversation, remote)
    return {
      conversation: await transport.save(workspace, merged),
      merged: true,
    }
  }
}

/**
 * Persist one queued snapshot against the latest canonical state known for its
 * workspace. Queued React effects intentionally capture their visible turn,
 * but must not capture the revision/canonical payload: an earlier queued save
 * may advance both before this write starts.
 *
 * The store is keyed by workspace so changing the visible workspace never
 * rebinds or drops a write that was already accepted into the queue.
 */
export async function persistQueuedWizardConversation(
  write: QueuedWizardConversationWrite,
  snapshots: WizardConversationSnapshotStore,
  transport: WizardConversationTransport = defaultTransport,
): Promise<WizardConversationSaveResult> {
  const canonical = snapshots.get(write.workspace)
  const outgoing = canonical
    ? mergeQueuedWizardConversationSnapshots(write.captured, write.base, canonical)
    : write.captured
  const saved = await saveWizardConversationWithRecovery(write.workspace, outgoing, transport, canonical)
  snapshots.set(write.workspace, saved.conversation)
  return saved
}

/**
 * Serialize browser conversation writes so every save reads the revision
 * confirmed by its predecessor. A rejected write does not poison the queue.
 */
export function enqueueWizardConversationSave(
  previous: Promise<void>,
  write: () => Promise<void>,
): Promise<void> {
  return previous.catch(() => undefined).then(write)
}
