import { useCallback, useEffect, useState } from 'react'
import { videoJsExampleDocument } from './examples.ts'
import { readVideoJsDraft, writeVideoJsDraft } from './storage.ts'
import type { VideoJsDocument } from './types.ts'

const HISTORY_LIMIT = 40
const COALESCE_MS = 1500

interface HistoryState {
  workspace: string
  document: VideoJsDocument
  past: VideoJsDocument[]
  lastKey: string | null
  lastAt: number
}

function initial(workspace: string): HistoryState {
  return { workspace, document: readVideoJsDraft(workspace) ?? videoJsExampleDocument(), past: [], lastKey: null, lastAt: 0 }
}

/** Pure reducer step, exported for tests. Rapid edits with the same key
 *  (typing a title) collapse into one undo step. */
export function commitHistory(state: HistoryState, next: VideoJsDocument, key: string | null, now: number): HistoryState {
  if (next === state.document) return state
  const coalesce = key !== null && key === state.lastKey && now - state.lastAt < COALESCE_MS
  return {
    ...state,
    document: next,
    past: coalesce ? state.past : [...state.past, state.document].slice(-HISTORY_LIMIT),
    lastKey: key,
    lastAt: now,
  }
}

export function undoHistory(state: HistoryState): HistoryState {
  const previous = state.past[state.past.length - 1]
  if (!previous) return state
  return { ...state, document: previous, past: state.past.slice(0, -1), lastKey: null, lastAt: 0 }
}

export function useVideoJsDocument(workspace: string) {
  const [state, setState] = useState(() => initial(workspace))
  // Switching workspace opens that workspace's draft (adjusted during render).
  if (state.workspace !== workspace) setState(initial(workspace))

  useEffect(() => {
    writeVideoJsDraft(state.workspace, state.document)
  }, [state.workspace, state.document])

  const commit = useCallback((update: VideoJsDocument | ((current: VideoJsDocument) => VideoJsDocument), key: string | null = null) => {
    setState(current => commitHistory(current, typeof update === 'function' ? update(current.document) : update, key, Date.now()))
  }, [])
  const undo = useCallback(() => setState(undoHistory), [])

  return { document: state.document, commit, undo, canUndo: state.past.length > 0 }
}
