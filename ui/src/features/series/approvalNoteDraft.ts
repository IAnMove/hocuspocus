import { safeStorageGet, safeStorageRemove, safeStorageSet } from '../../lib/safeStorage'

type NoteDraft = { text: string; id?: string; stamp: string }
const keyFor = (scope: string) => `hocuspocus:approval-note:${scope}`
const saves = new Map<string, Promise<string | undefined>>()

export function readApprovalNote(scope: string): NoteDraft | undefined {
  try {
    const value = JSON.parse(safeStorageGet('session', keyFor(scope)) || 'null')
    return value && typeof value.text === 'string' && typeof value.stamp === 'string' ? value : undefined
  } catch { return undefined }
}

export function writeApprovalNote(scope: string, text: string, id?: string) {
  const stamp = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}:${Math.random()}`
  safeStorageSet('session', keyFor(scope), JSON.stringify({ text, id, stamp }))
}

/** Serializes this note even across a card remount. Only its acknowledged snapshot is removed. */
export function saveApprovalNote(scope: string, send: (note: NoteDraft) => Promise<string | undefined>) {
  const task = (saves.get(scope) ?? Promise.resolve<string | undefined>(undefined)).catch(() => undefined).then(async previousId => {
    const draft = readApprovalNote(scope)
    if (!draft) return previousId
    const id = await send(draft)
    const latest = readApprovalNote(scope)
    if (latest?.stamp === draft.stamp) safeStorageRemove('session', keyFor(scope))
    else if (latest) safeStorageSet('session', keyFor(scope), JSON.stringify({ ...latest, id }))
    return id
  })
  saves.set(scope, task)
  void task.finally(() => { if (saves.get(scope) === task) saves.delete(scope) }).catch(() => {})
  return task
}
