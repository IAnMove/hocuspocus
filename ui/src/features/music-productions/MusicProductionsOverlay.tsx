import { MusicProductionsPanel } from './MusicProductionsPanel'

export function MusicProductionsOverlay({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null
  return <div className="fixed inset-0 z-[110] flex flex-col bg-bg-primary" role="dialog" aria-modal="true">
    <MusicProductionsPanel onClose={onClose} />
  </div>
}
