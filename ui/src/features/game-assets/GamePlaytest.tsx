import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { useUiTranslation } from '../../i18n'
import { codeLabel, gameText } from './gameErrors'
import { integerScale, PLAY_HEIGHT, PLAY_WIDTH, playtestScene, type PlayMissing, type PlayScene } from './playtestScene'
import { PlaytestRuntime } from './playtestRuntime'
import { useGameAssetsStore } from './store'
import { buttonClass, errorClass, panelClass } from './styles'
import type { Game } from './types'

/** The scene as text: a refresh that changes nothing the playtest draws keeps the same string, so the game does not restart. */
function sceneText(game: Game | null): string {
  return game ? JSON.stringify(playtestScene(game)) : ''
}

function missingLabel(item: PlayMissing): string {
  const name = item.code === 'animation' ? codeLabel('playActions', item.name) : codeLabel('playTriggers', item.name)
  return gameText(`playMissingItems.${item.code}`, { name })
}

function fittedWidth(view: number): number {
  if (view > 0 && view < PLAY_WIDTH) return Math.max(1, Math.floor(view))
  return PLAY_WIDTH * integerScale(view || PLAY_WIDTH)
}

export function GamePlaytest() {
  const { t } = useUiTranslation('gameAssets')
  const text = useGameAssetsStore(state => sceneText(state.game))
  const workspace = useGameAssetsStore(state => state.workspace)
  const scene = useMemo<PlayScene | null>(() => (text ? JSON.parse(text) as PlayScene : null), [text])
  const ready = scene !== null
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const runtimeRef = useRef<PlaytestRuntime | null>(null)
  const sceneRef = useRef<PlayScene | null>(null)
  const mutedRef = useRef(false)
  const [muted, setMuted] = useState(false)
  const [audioFailed, setAudioFailed] = useState(false)
  const [cssWidth, setCssWidth] = useState(PLAY_WIDTH)
  const helpId = useId()

  useEffect(() => {
    sceneRef.current = scene
    runtimeRef.current?.setScene(scene)
  }, [scene])

  useEffect(() => {
    mutedRef.current = muted
    runtimeRef.current?.setMuted(muted)
  }, [muted])

  // One runtime per canvas and workspace; leaving the tab or the panel disposes it.
  useEffect(() => {
    const ctx = ready ? canvasRef.current?.getContext('2d') : null
    if (!ctx) return undefined
    const runtime = new PlaytestRuntime(ctx, workspace, { onAudioError: () => setAudioFailed(true) })
    runtime.setMuted(mutedRef.current)
    runtime.setScene(sceneRef.current)
    runtime.start()
    runtimeRef.current = runtime
    const onVisibility = () => runtime.setHidden(document.visibilityState === 'hidden')
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      runtime.dispose()
      runtimeRef.current = null
    }
  }, [ready, workspace])

  useEffect(() => {
    const node = wrapRef.current
    if (!ready || !node || typeof ResizeObserver === 'undefined') return undefined
    const apply = () => setCssWidth(fittedWidth(node.clientWidth))
    apply()
    const observer = new ResizeObserver(apply)
    observer.observe(node)
    return () => observer.disconnect()
  }, [ready])

  // Keys reach the game only while its canvas has focus; text fields elsewhere keep Space and the arrows.
  const onKey = (down: boolean) => (event: KeyboardEvent<HTMLCanvasElement>) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return
    if (runtimeRef.current?.key(event.key, down)) event.preventDefault()
  }

  if (!scene) return null
  return (
    <div className="space-y-3" ref={wrapRef}>
      <p id={helpId} className="text-sm text-muted-foreground">{t('playControls')}</p>
      <canvas
        ref={canvasRef}
        width={PLAY_WIDTH}
        height={PLAY_HEIGHT}
        tabIndex={0}
        role="application"
        aria-label={t('playCanvas')}
        aria-describedby={helpId}
        className="h-auto max-w-full border border-border bg-black focus:outline focus:outline-2 focus:outline-offset-2"
        style={{ width: cssWidth, imageRendering: 'pixelated' }}
        onKeyDown={onKey(true)}
        onKeyUp={onKey(false)}
        onBlur={() => runtimeRef.current?.releaseKeys()}
        onPointerDown={event => {
          event.currentTarget.focus()
          runtimeRef.current?.unlockAudio()
        }}
      />
      <button type="button" className={buttonClass} aria-pressed={muted} onClick={() => setMuted(value => !value)}>{t('mute')}</button>
      {audioFailed && <p role="alert" className={errorClass}>{t('couldNotPlay')}</p>}
      {scene.missing.length > 0 && (
        <div className={panelClass}>
          <p className="text-sm">{t('playMissing')}</p>
          <ul className="list-disc pl-5">
            {scene.missing.map(item => <li key={`${item.code}-${item.name}`} className="text-sm">{missingLabel(item)}</li>)}
          </ul>
        </div>
      )}
    </div>
  )
}
