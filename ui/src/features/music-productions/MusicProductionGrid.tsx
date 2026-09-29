import { useUiTranslation } from '../../i18n'
import { musicProductionFileUrl } from './fileUrl'
import type { MusicProductionShot, MusicProductionTake } from './types'

const buttonClass = 'inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-[11px] hover:bg-bg-hover disabled:opacity-50'

export function MusicProductionGrid({
  workspace,
  shots,
  busy,
  onOpenScene,
  onRetake,
  onUseTake,
  onOpenMontage,
}: {
  workspace: string
  shots: MusicProductionShot[]
  busy?: boolean
  onOpenScene: (sceneName: string) => void
  onRetake: (shot: string) => void
  onUseTake: (shot: string, takeFile: string) => void
  onOpenMontage: () => void
}) {
  const { t } = useUiTranslation('navigation')
  return <div className="flex flex-col gap-3">
    <div>
      <button type="button" className={buttonClass} onClick={onOpenMontage}>{t('musicProductions.openMontage')}</button>
    </div>
    <div className="grid gap-3 sm:grid-cols-2">
      {shots.map(shot => <ShotCard
        key={shot.key}
        workspace={workspace}
        shot={shot}
        busy={busy}
        onOpenScene={onOpenScene}
        onRetake={onRetake}
        onUseTake={onUseTake}
      />)}
    </div>
  </div>
}

function ShotCard({
  workspace, shot, busy, onOpenScene, onRetake, onUseTake,
}: {
  workspace: string
  shot: MusicProductionShot
  busy?: boolean
  onOpenScene: (sceneName: string) => void
  onRetake: (shot: string) => void
  onUseTake: (shot: string, takeFile: string) => void
}) {
  const { t } = useUiTranslation('navigation')
  const frame = musicProductionFileUrl(workspace, shot.start_frame)
  const takes = shot.takes || []
  return <article className="flex flex-col gap-2 rounded border border-border bg-bg-secondary p-3">
    {frame ? <img src={frame} alt={shot.key} className="aspect-video w-full rounded object-cover" /> : null}
    <header className="flex items-baseline justify-between gap-2">
      <h3 className="text-sm font-medium text-text-primary">{shot.key}</h3>
      <span className="text-[11px] text-text-secondary">{shot.sung ? t('musicProductions.sung') : t('musicProductions.notSung')}</span>
    </header>
    <p className="text-xs text-text-primary">{shot.lyric || t('musicProductions.lyric')}</p>
    <p className="text-[11px] text-text-secondary">{t('musicProductions.clip')}: {shot.clip || '—'}</p>
    <p className="text-[11px] text-text-secondary">{t('musicProductions.scene')}: {shot.scene_doc || '—'}</p>
    <div className="flex flex-col gap-1">
      <span className="text-[11px] text-text-secondary">{t('musicProductions.takes')}</span>
      {takes.length === 0 ? <span className="text-[11px] text-text-secondary">{t('musicProductions.noTakes')}</span> : null}
      {takes.map(take => <TakeRow key={take.file} shot={shot.key} take={take} busy={busy} onUseTake={onUseTake} />)}
    </div>
    <div className="flex flex-wrap gap-1">
      <button type="button" className={buttonClass} disabled={busy || !shot.scene_doc} onClick={() => shot.scene_doc && onOpenScene(shot.scene_doc)}>
        {t('musicProductions.openScene')}
      </button>
      <button type="button" className={buttonClass} disabled={busy} onClick={() => onRetake(shot.key)}>
        {t('musicProductions.anotherTake')}
      </button>
    </div>
  </article>
}

function TakeRow({
  shot, take, busy, onUseTake,
}: {
  shot: string
  take: MusicProductionTake
  busy?: boolean
  onUseTake: (shot: string, takeFile: string) => void
}) {
  const { t } = useUiTranslation('navigation')
  const label = t('musicProductions.useTake')
  return <div className="flex items-center justify-between gap-2">
    <span className="truncate text-[11px] text-text-primary">{take.file}{typeof take.r === 'number' ? ` · r ${take.r}` : ''}</span>
    <button
      type="button"
      className={buttonClass}
      disabled={busy}
      aria-label={`${label} ${take.file}`}
      onClick={() => onUseTake(shot, take.file)}
    >{label}</button>
  </div>
}
