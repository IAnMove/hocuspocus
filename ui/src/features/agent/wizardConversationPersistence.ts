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

const defaultTransport: WizardConversationTransport = {
  fetch: fetchWizardConversation,
  save: saveWizardConversation,
}

function stableKey(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value) ?? String(value)
  if (Array.isArray(value)) return `[${value.map(stableKey).join(',')}]`
  const record = value as Record<string, unknown>
  return `{${Object.keys(record).sort().map(key => `${JSON.stringify(key)}:${stableKey(record[key])}`).join(',')}}`
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
): Promise<WizardConversationSaveResult> {
  try {
    return {
      conversation: await transport.save(workspace, conversation),
      merged: false,
    }
  } catch (error) {
    if (!isWizardConversationConflict(error)) throw error
    const remote = await transport.fetch(workspace)
    const merged = mergeWizardConversationSnapshots(conversation, remote)
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
  workspace: string,
  captured: WizardConversationPayload,
  snapshots: WizardConversationSnapshotStore,
  transport: WizardConversationTransport = defaultTransport,
): Promise<WizardConversationSaveResult> {
  const canonical = snapshots.get(workspace)
  const outgoing = canonical
    ? mergeWizardConversationSnapshots(captured, canonical)
    : captured
  const saved = await saveWizardConversationWithRecovery(workspace, outgoing, transport)
  snapshots.set(workspace, saved.conversation)
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
