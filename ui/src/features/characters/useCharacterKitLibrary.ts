import { useCallback, useEffect, useState } from 'react'
import { fetchCharacterKitLibrary } from '../../api/characters'
import { listCharacterKits, type CharacterKit } from '../../lib/characterKit'

export function useCharacterKitLibrary(workspace: string, requireSpeech3d = false, enabled = true) {
  const [state, setState] = useState<{ workspace: string; kits: CharacterKit[]; error?: string }>()
  const [version, setVersion] = useState(0)
  const reload = useCallback(() => setVersion(value => value + 1), [])
  useEffect(() => {
    if (!enabled) return
    let live = true
    void fetchCharacterKitLibrary(workspace)
      .then(result => {
        if (live) setState({ workspace, kits: listCharacterKits(result, { requireSpeech3d }) })
      })
      .catch(reason => {
        if (live) setState({ workspace, kits: [], error: reason instanceof Error ? reason.message : String(reason) })
      })
    return () => { live = false }
  }, [workspace, requireSpeech3d, enabled, version])
  const kits = state?.workspace === workspace ? state.kits : []
  const error = state?.workspace === workspace ? state.error : undefined
  return { kits, error, reload }
}
