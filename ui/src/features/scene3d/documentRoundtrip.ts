import { useMemo } from 'react'
import { parseScene3DDocument } from './document'
import type { Scene3DDocument } from './types'

/** True when the document survives a JSON save/load unchanged enough to parse. */
export function documentRoundtrips(document: Scene3DDocument): boolean {
  return Boolean(parseScene3DDocument(JSON.parse(JSON.stringify(document))))
}

/** Memoised per document: playback re-renders at 30–60 Hz must not re-serialise it. */
export function useDocumentRoundtrip(document: Scene3DDocument, check: (document: Scene3DDocument) => boolean = documentRoundtrips): boolean {
  return useMemo(() => check(document), [document, check])
}
