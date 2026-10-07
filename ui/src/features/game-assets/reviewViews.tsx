import { useEffect, useState } from 'react'
import { AudioVariants, MusicLoopPlayer } from './AudioLoopPlayer'
import { GlbPreview } from './GlbPreview'
import { SpriteSheetPlayer } from './SpriteSheetPlayer'
import { atlasFrames, clipNames, fileUrl, layerFiles, loopSamples, modelFile, musicFile, playbackSources, sheetFile, stillFile } from './reviewModel'
import type { GameAsset, GameAttempt } from './types'

const AUDIO = new Set(['sfx', 'music', 'jingle', 'voice'])
const SHEET = new Set(['animation', 'vfx'])

export function AttemptPreview({ asset, attempt, pixel, workspace }: { asset: GameAsset; attempt: GameAttempt; pixel: boolean; workspace: string }) {
  const files = attempt.files || {}
  if (AUDIO.has(asset.kind)) return <AudioPreview kind={asset.kind} files={files} attempt={attempt} workspace={workspace} />
  if (asset.kind === 'model3d' || asset.kind === 'character3d') {
    return <GlbPreview url={fileUrl(modelFile(files), workspace)} clips={clipNames(attempt.metrics)} />
  }
  if (asset.kind === 'background') return <LayerStack files={files} workspace={workspace} pixel={pixel} />
  if (asset.kind === 'tile') return <Repeat url={fileUrl(stillFile(files), workspace)} pixel={pixel} across={4} down={4} />
  if (asset.kind === 'tileset') return <Tileset url={fileUrl(stillFile(files), workspace)} pixel={pixel} />
  if (SHEET.has(asset.kind)) return <Sheet files={files} workspace={workspace} pixel={pixel} />
  return <Still url={fileUrl(stillFile(files), workspace)} pixel={pixel} name={asset.name} />
}

function Still({ url, pixel, name }: { url: string; pixel: boolean; name: string }) {
  if (!url) return null
  return <img src={url} alt={name} className="max-h-48 max-w-full" style={{ imageRendering: pixel ? 'pixelated' : 'auto' }} />
}

function Repeat({ url, pixel, across, down }: { url: string; pixel: boolean; across: number; down: number }) {
  if (!url) return null
  const cell = 48
  return (
    <div
      role="img"
      style={{
        width: cell * across,
        height: cell * down,
        backgroundImage: `url(${url})`,
        backgroundSize: `${cell}px ${cell}px`,
        imageRendering: pixel ? 'pixelated' : 'auto',
      }}
    />
  )
}

function Tileset({ url, pixel }: { url: string; pixel: boolean }) {
  return (
    <div className="space-y-2">
      <Repeat url={url} pixel={pixel} across={3} down={3} />
      <Repeat url={url} pixel={pixel} across={6} down={1} />
    </div>
  )
}

function LayerStack({ files, workspace, pixel }: { files: Record<string, string>; workspace: string; pixel: boolean }) {
  const layers = layerFiles(files)
  const urls = layers.length ? layers : [stillFile(files)].filter(Boolean)
  return (
    <div className="relative h-40 overflow-hidden rounded-md border border-border">
      <style>{'@keyframes game-layer-shift { from { transform: translateX(0); } to { transform: translateX(-12%); } }'}</style>
      {urls.map((file, index) => (
        <img
          key={file}
          src={fileUrl(file, workspace)}
          alt=""
          className="absolute inset-0 h-full w-[120%] max-w-none object-cover"
          style={{ imageRendering: pixel ? 'pixelated' : 'auto', animation: `game-layer-shift ${14 + index * 6}s linear infinite` }}
        />
      ))}
    </div>
  )
}

/** The sheet animates from its atlas; a missing or unreadable atlas shows the still sheet. */
function Sheet({ files, workspace, pixel }: { files: Record<string, string>; workspace: string; pixel: boolean }) {
  const atlasUrl = files.atlas ? fileUrl(files.atlas, workspace) : ''
  const [loaded, setLoaded] = useState<{ url: string; atlas: unknown } | null>(null)
  const sheet = fileUrl(sheetFile(files), workspace)
  useEffect(() => {
    if (!atlasUrl) return undefined
    let cancel = false
    const done = (atlas: unknown) => { if (!cancel) setLoaded({ url: atlasUrl, atlas }) }
    fetch(atlasUrl).then(response => response.ok ? response.json() : null).then(done, () => done(null))
    return () => { cancel = true }
  }, [atlasUrl])
  const atlas = loaded?.url === atlasUrl ? loaded.atlas : null
  if (atlas && atlasFrames(atlas).length) return <SpriteSheetPlayer imageUrl={sheet} atlas={atlas} pixel={pixel} />
  return <Still url={sheet} pixel={pixel} name="" />
}

/** Music loops (or any take with loop points); SFX variants, jingles and voices just play. */
function AudioPreview({ kind, files, attempt, workspace }: { kind: string; files: Record<string, string>; attempt: GameAttempt; workspace: string }) {
  const loop = loopSamples(attempt.metrics)
  if (kind === 'music' || loop) {
    const url = fileUrl(musicFile(files), workspace)
    return <MusicLoopPlayer key={url} url={url} loop={loop} />
  }
  const sources = playbackSources(files).map(item => ({ key: item.key, url: fileUrl(item.file, workspace) }))
  return <AudioVariants sources={sources} />
}
