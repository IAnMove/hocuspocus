import { useEffect, useMemo, useRef, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { fileUrl } from './reviewModel'
import { GROUND_Y, integerScale, PLAY_HEIGHT, PLAY_WIDTH, playtestScene, stepBody, type Body, type PlayInput, type PlayScene } from './playtestScene'
import { useGameAssetsStore } from './store'
import { buttonClass, panelClass } from './styles'

const images = new Map<string, HTMLImageElement>()

export function GamePlaytest() {
  const { t } = useUiTranslation('gameAssets')
  const game = useGameAssetsStore(state => state.game)
  const workspace = useGameAssetsStore(state => state.workspace)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const keys = useRef<PlayInput & { attack: boolean }>({ left: false, right: false, run: false, jump: false, attack: false })
  const mutedRef = useRef(false)
  const [muted, setMuted] = useState(false)
  const [cssWidth, setCssWidth] = useState(PLAY_WIDTH)
  const scene = useMemo(() => (game ? playtestScene(game) : null), [game])

  useEffect(() => {
    mutedRef.current = muted
  }, [muted])

  useEffect(() => {
    const onDown = (event: KeyboardEvent) => setKey(keys.current, event, true)
    const onUp = (event: KeyboardEvent) => setKey(keys.current, event, false)
    window.addEventListener('keydown', onDown)
    window.addEventListener('keyup', onUp)
    return () => {
      window.removeEventListener('keydown', onDown)
      window.removeEventListener('keyup', onUp)
    }
  }, [])

  useEffect(() => {
    const node = wrapRef.current
    if (!node || typeof ResizeObserver === 'undefined') return undefined
    const apply = () => setCssWidth(fittedWidth(node.clientWidth))
    apply()
    const observer = new ResizeObserver(apply)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx || !scene) return undefined
    let body: Body = { x: 80, y: GROUND_Y, vx: 0, vy: 0, onGround: true }
    let last = 0
    let frame = 0
    let id = 0
    const heard = { attack: false, coins: [] as boolean[] }
    const loop = (now: number) => {
      const dt = last ? (now - last) / 1000 : 0.016
      last = now
      const grounded = body.onGround
      body = stepBody(body, keys.current, dt)
      hear(scene, workspace, body, keys.current, grounded, heard, mutedRef.current)
      paintPlay(ctx, scene, workspace, body, keys.current, frame)
      frame += 1
      id = requestAnimationFrame(loop)
    }
    id = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(id)
  }, [scene, workspace])

  if (!scene) return null
  return (
    <div className="space-y-3" ref={wrapRef}>
      <canvas ref={canvasRef} width={PLAY_WIDTH} height={PLAY_HEIGHT} className="h-auto max-w-full border border-border bg-black" style={{ width: cssWidth, imageRendering: 'pixelated' }} />
      <button type="button" className={buttonClass} aria-pressed={muted} onClick={() => setMuted(value => !value)}>{muted ? t('unmute') : t('mute')}</button>
      {scene.music && !muted && <audio src={fileUrl(scene.music, workspace)} autoPlay loop />}
      {scene.missing.length > 0 && (
        <div className={panelClass}>
          <p className="text-sm">{t('playMissing')}</p>
          {scene.missing.map(item => <p key={item} className="text-sm">{item}</p>)}
        </div>
      )}
    </div>
  )
}

function fittedWidth(view: number): number {
  if (view > 0 && view < PLAY_WIDTH) return Math.max(1, Math.floor(view))
  return PLAY_WIDTH * integerScale(view || PLAY_WIDTH)
}

function setKey(keys: PlayInput & { attack: boolean }, event: KeyboardEvent, down: boolean): void {
  if (event.key === 'ArrowLeft') keys.left = down
  if (event.key === 'ArrowRight') keys.right = down
  if (event.key === 'Shift') keys.run = down
  if (event.key === ' ') {
    keys.jump = down
    if (down) event.preventDefault()
  }
  if (event.key === 'x' || event.key === 'X') keys.attack = down
}

function hear(scene: PlayScene, workspace: string, body: Body, input: PlayInput & { attack: boolean }, grounded: boolean, heard: { attack: boolean; coins: boolean[] }, muted: boolean): void {
  if (grounded && !body.onGround) playTrigger(scene, workspace, 'jump', muted)
  if (input.attack && !heard.attack) playTrigger(scene, workspace, 'hit', muted)
  heard.attack = input.attack
  scene.items.forEach((_item, index) => {
    if (heard.coins[index]) return
    if (Math.abs(body.x - (180 + index * 48)) >= 28) return
    heard.coins[index] = true
    playTrigger(scene, workspace, 'coin', muted)
  })
}

function playTrigger(scene: PlayScene, workspace: string, trigger: string, muted: boolean): void {
  if (muted) return
  const file = scene.sfxByTrigger[trigger]
  if (!file || typeof Audio === 'undefined') return
  const audio = new Audio(fileUrl(file, workspace))
  void audio.play().catch(() => undefined)
}

function paintPlay(ctx: CanvasRenderingContext2D, scene: PlayScene, workspace: string, body: Body, input: PlayInput & { attack: boolean }, frame: number): void {
  ctx.imageSmoothingEnabled = false
  ctx.fillStyle = '#0b1020'
  ctx.fillRect(0, 0, PLAY_WIDTH, PLAY_HEIGHT)
  scene.layers.forEach((layer, index) => drawImageOrLabel(ctx, fileUrl(layer.file, workspace), layer.file, (frame * layer.factor) % PLAY_WIDTH, 40 + index * 30, PLAY_WIDTH, 80))
  const tile = scene.tiles[0]
  for (let x = 0; x < PLAY_WIDTH; x += 40) {
    drawImageOrLabel(ctx, tile ? fileUrl(tile.file, workspace) : '', tile?.name || 'tile', x, GROUND_Y + 8, 40, 40)
  }
  const heroFile = scene.hero?.sheets[heroAction(input, body)] || scene.hero?.still || ''
  drawActor(ctx, fileUrl(heroFile, workspace), scene.hero?.name || 'hero', body.x, body.y - 48, input.left)
  scene.enemies.forEach((enemy, index) => {
    drawActor(ctx, fileUrl(enemy.file, workspace), enemy.name, 420 + Math.sin(frame / 40 + index) * 70, GROUND_Y - 36, false)
  })
  scene.items.forEach((item, index) => {
    drawImageOrLabel(ctx, fileUrl(item.file, workspace), item.name, 180 + index * 48, GROUND_Y - 70 + Math.sin(frame / 20 + index) * 6, 24, 24)
  })
}

function heroAction(input: PlayInput & { attack: boolean }, body: Body): string {
  if (input.attack) return 'attack'
  if (input.jump && !body.onGround) return 'jump'
  if (input.run && (input.left || input.right)) return 'run'
  if (input.left || input.right) return 'walk'
  return 'idle'
}

function drawActor(ctx: CanvasRenderingContext2D, url: string, name: string, x: number, y: number, mirror: boolean): void {
  ctx.save()
  if (mirror) {
    ctx.translate(x + 32, y)
    ctx.scale(-1, 1)
    drawImageOrLabel(ctx, url, name, 0, 0, 32, 48)
  } else {
    drawImageOrLabel(ctx, url, name, x, y, 32, 48)
  }
  ctx.restore()
}

function drawImageOrLabel(ctx: CanvasRenderingContext2D, url: string, name: string, x: number, y: number, width: number, height: number): void {
  const image = loaded(url)
  if (image) {
    ctx.drawImage(image, x, y, width, height)
    return
  }
  ctx.fillStyle = '#1e293b'
  ctx.fillRect(x, y, width, height)
  ctx.fillStyle = '#e8e8ef'
  ctx.font = '12px sans-serif'
  ctx.fillText(name, x + 2, y + 14)
}

function loaded(url: string): HTMLImageElement | null {
  if (!url) return null
  let image = images.get(url)
  if (!image) {
    image = new Image()
    image.src = url
    images.set(url, image)
  }
  return image.complete && image.naturalWidth ? image : null
}
