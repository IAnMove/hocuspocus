import type { StoryLibraryConflict } from './library'

export function StoryLibraryConflictNotice({
  conflicts,
  onResolve,
}: {
  conflicts: StoryLibraryConflict[]
  onResolve: (id: string, resolution: 'local' | 'remote') => void
}) {
  if (!conflicts.length) return null
  return (
    <div role="alert" className="mt-2 rounded-md border border-amber-400/60 bg-amber-500/10 px-2.5 py-2 text-[10px] text-amber-100">
      <p className="font-semibold">Story library conflict: review before saving</p>
      <p className="mt-0.5 text-amber-200/80">
        Local and remote copies have the same timestamp but different content. The local copy is shown and neither copy will overwrite the other.
      </p>
      <ul className="mt-1 space-y-1.5">
        {conflicts.map(conflict => (
          <li key={conflict.id} className="flex flex-wrap items-center gap-1.5">
            <span className="mr-auto font-medium">{conflict.title}</span>
            <button type="button" className="rounded border border-amber-300/40 px-1.5 py-0.5 hover:bg-amber-300/10" onClick={() => onResolve(conflict.id, 'local')}>
              Keep local
            </button>
            <button type="button" className="rounded border border-amber-300/40 px-1.5 py-0.5 hover:bg-amber-300/10" onClick={() => onResolve(conflict.id, 'remote')}>
              Use remote
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
