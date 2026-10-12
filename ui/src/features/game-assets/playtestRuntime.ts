import { LoopEngine } from './audioLoop'
import { fileUrl } from './reviewModel'
import { GROUND_Y, PLAY_HEIGHT, PLAY_WIDTH, stepBody, type Anchor, type Body, type PlayActor, type PlayGround, type PlayScene, type PlaySprite, type SfxTrigger } from './playtestScene'
import {
  applyKey, cameraFor, clipFrameIndex, clipLength, heroAction, layerOffsets, releaseKeys, sheetClip, spriteBox, stillClip, tilesetCells,
  type PlayKeys, type SheetClip, type TileRect,
} from './playtestSprites'

/** What the runtime needs from a music player; ``LoopEngine`` in the app. */
export interface MusicPlayer {
  play(fromSeam: boolean): Promise<void>
  stop(): void
  suspend(): void
  resume(): void
  close(): void
}

/** What the runtime needs from a sound effect; ``HTMLAudioElement`` in the app. */
export interface SoundPlayer {
  play(): Promise<void>
  pause(): void
  addEventListener(type: 'ended', listener: () => void): void
}

export interface RuntimeOptions {
  requestFrame?: (callback: FrameRequestCallback) => number
  cancelFrame?: (id: number) => void
  fetchJson?: (url: string, signal: AbortSignal) => Promise<unknown>
  createMusic?: (url: string, loop: { start: number; end: number } | null) => MusicPlayer
  createSound?: (url: string) => SoundPlayer | null
  onAudioError?: () => void
}

interface Box { w: number; h: number }

const HERO_BOX: Box = { w: 32, h: 48 }
const ENEMY_BOX: Box = { w: 32, h: 40 }
const ITEM_BOX: Box = { w: 24, h: 24 }
const ATTACK_MS = 300

export const itemX = (index: number) => 260 + index * 120
export const enemyX = (index: number) => 760 + index * 320

async function fetchJson(url: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(url, { signal })
  return response.ok ? response.json() : null
}

function newSound(url: string): SoundPlayer | null {
  return typeof Audio === 'undefined' ? null : new Audio(url)
}

/** Images and JSON sidecars of one workspace; ``dispose`` aborts pending reads and drops every image. */
class PlayMedia {
  private readonly images = new Map<string, HTMLImageElement>()
  private readonly data = new Map<string, unknown>()
  private readonly abort = new AbortController()
  private readonly workspace: string
  private readonly read: (url: string, signal: AbortSignal) => Promise<unknown>

  constructor(workspace: string, read: (url: string, signal: AbortSignal) => Promise<unknown>) {
    this.workspace = workspace
    this.read = read
  }

  image(file: string): HTMLImageElement | null {
    if (!file || typeof Image === 'undefined' || this.abort.signal.aborted) return null
    let image = this.images.get(file)
    if (!image) {
      image = new Image()
      image.src = fileUrl(file, this.workspace)
      this.images.set(file, image)
    }
    return image.complete && image.naturalWidth > 0 ? image : null
  }

  /** The parsed JSON, ``undefined`` while it loads, ``null`` when it could not be read. */
  json(file: string): unknown {
    if (!file) return null
    if (this.data.has(file)) return this.data.get(file)
    this.data.set(file, undefined)
    const signal = this.abort.signal
    const keep = (value: unknown) => { if (!signal.aborted) this.data.set(file, value ?? null) }
    this.read(fileUrl(file, this.workspace), signal).then(keep, () => keep(null))
    return undefined
  }

  dispose(): void {
    this.abort.abort()
    for (const image of this.images.values()) image.removeAttribute('src')
    this.images.clear()
    this.data.clear()
  }
}

/**
 * The side-view playtest: one ``requestAnimationFrame`` loop, its media, music and sound effects.
 * ``dispose`` cancels the frame, aborts reads, closes the AudioContext and stops every sound.
 */
export class PlaytestRuntime {
  readonly keys: PlayKeys = { left: false, right: false, run: false, jump: false, attack: false }
  private readonly ctx: CanvasRenderingContext2D
  private readonly workspace: string
  private readonly options: RuntimeOptions
  private readonly media: PlayMedia
  private readonly clips = new Map<string, SheetClip | null>()
  private readonly sounds = new Set<SoundPlayer>()
  private scene: PlayScene | null = null
  private body: Body = { x: 80, y: GROUND_Y, vx: 0, vy: 0, onGround: true }
  private frameId = 0
  private last = 0
  private now = 0
  private disposed = false
  private facingLeft = false
  private action = 'idle'
  private actionStart = 0
  private attackStart = Number.NEGATIVE_INFINITY
  private attackHeld = false
  private collected = new Set<number>()
  private muted = false
  private audioUnlocked = false
  private music: MusicPlayer | null = null
  private musicKey = ''
  private sfxTurn = 0

  constructor(ctx: CanvasRenderingContext2D, workspace: string, options: RuntimeOptions = {}) {
    this.ctx = ctx
    this.workspace = workspace
    this.options = options
    this.media = new PlayMedia(workspace, options.fetchJson || fetchJson)
  }

  /** A new scene keeps the hero where it is; only a different music take restarts the music. */
  setScene(scene: PlayScene | null): void {
    this.scene = scene
    const key = scene?.music ? JSON.stringify(scene.music) : ''
    if (key === this.musicKey) return
    this.musicKey = key
    this.music?.close()
    this.music = null
    if (this.audioUnlocked && !this.muted) this.startMusic()
  }

  start(): void {
    if (this.frameId || this.disposed) return
    const request = this.options.requestFrame || (callback => globalThis.requestAnimationFrame(callback))
    const tick = (now: number) => {
      this.frameId = 0
      if (this.disposed) return
      this.step(now)
      this.frameId = request(tick)
    }
    this.frameId = request(tick)
  }

  dispose(): void {
    this.disposed = true
    if (this.frameId) (this.options.cancelFrame || (id => globalThis.cancelAnimationFrame(id)))(this.frameId)
    this.frameId = 0
    releaseKeys(this.keys)
    this.music?.close()
    this.music = null
    this.stopSounds()
    this.media.dispose()
    this.clips.clear()
  }

  /** ``true`` when the game uses ``key``; the caller then prevents its default (scrolling). */
  key(key: string, down: boolean): boolean {
    const handled = applyKey(this.keys, key, down)
    if (handled && down) this.unlockAudio()
    return handled
  }

  /** Focus left the game: no key stays held down. */
  releaseKeys(): void {
    releaseKeys(this.keys)
  }

  setHidden(hidden: boolean): void {
    if (hidden) {
      releaseKeys(this.keys)
      this.music?.suspend()
    } else {
      this.music?.resume()
    }
  }

  setMuted(muted: boolean): void {
    this.muted = muted
    if (muted) {
      this.music?.stop()
      this.stopSounds()
    } else if (this.audioUnlocked) {
      this.startMusic()
    }
  }

  /** Browsers start audio only after a gesture, so music waits for the first key or click in the game. */
  unlockAudio(): void {
    if (this.audioUnlocked || this.disposed) return
    this.audioUnlocked = true
    if (!this.muted) this.startMusic()
  }

  private startMusic(): void {
    const music = this.scene?.music
    if (!music || this.disposed) return
    const url = fileUrl(music.file, this.workspace)
    this.music = this.music || (this.options.createMusic || ((source, loop) => new LoopEngine(source, loop)))(url, music.loop)
    this.music.play(false).catch(() => this.options.onAudioError?.())
  }

  private stopSounds(): void {
    for (const sound of this.sounds) sound.pause()
    this.sounds.clear()
  }

  private playSfx(trigger: SfxTrigger): void {
    const files = this.scene?.sfx[trigger] || []
    if (this.muted || this.disposed || !files.length) return
    const file = files[this.sfxTurn % files.length]
    this.sfxTurn += 1
    const sound = (this.options.createSound || newSound)(fileUrl(file, this.workspace))
    if (!sound) return
    this.sounds.add(sound)
    sound.addEventListener('ended', () => this.sounds.delete(sound))
    sound.play().catch(() => this.sounds.delete(sound))
  }

  private step(now: number): void {
    const dt = this.last ? (now - this.last) / 1000 : 1 / 60
    this.last = now
    this.now = now
    const scene = this.scene
    if (!scene) return
    const grounded = this.body.onGround
    this.body = stepBody(this.body, this.keys, dt)
    if (this.keys.left !== this.keys.right) this.facingLeft = this.keys.left
    this.hear(scene, grounded)
    this.paint(scene)
  }

  private hear(scene: PlayScene, grounded: boolean): void {
    if (grounded && !this.body.onGround) this.playSfx('jump')
    if (this.keys.attack && !this.attackHeld) {
      this.attackStart = this.now
      this.playSfx('hit')
    }
    this.attackHeld = this.keys.attack
    scene.items.forEach((_item, index) => {
      if (this.collected.has(index) || Math.abs(this.body.x - itemX(index)) >= 20) return
      this.collected.add(index)
      this.playSfx('coin')
    })
  }

  private paint(scene: PlayScene): void {
    const ctx = this.ctx
    ctx.imageSmoothingEnabled = false
    ctx.fillStyle = '#0b1020'
    ctx.fillRect(0, 0, PLAY_WIDTH, PLAY_HEIGHT)
    const camera = Math.round(cameraFor(this.body.x))
    this.paintLayers(scene, camera)
    this.paintGround(scene.ground, camera)
    scene.items.forEach((item, index) => {
      if (this.collected.has(index)) return
      const bob = Math.round(Math.sin(this.now / 300 + index) * 3)
      this.drawActor(item, itemX(index) - camera, GROUND_Y - 40 + bob, false, ITEM_BOX)
    })
    scene.enemies.forEach((enemy, index) => {
      const phase = this.now / 1400 + index
      this.drawActor(enemy, enemyX(index) + Math.sin(phase) * 70 - camera, GROUND_Y - 1, Math.cos(phase) < 0, ENEMY_BOX)
    })
    this.paintHero(scene, camera)
    this.paintVfx(scene, camera)
  }

  private paintLayers(scene: PlayScene, camera: number): void {
    for (const layer of scene.layers) {
      const image = this.media.image(layer.file)
      if (!image) continue
      const width = Math.round(image.naturalWidth * PLAY_HEIGHT / image.naturalHeight)
      for (const x of layerOffsets(camera, layer.factor, width, scene.loopX)) this.ctx.drawImage(image, Math.round(x), 0, width, PLAY_HEIGHT)
    }
  }

  private groundCells(ground: PlayGround, image: HTMLImageElement): { top: TileRect; fill: TileRect } | null {
    if (!ground.tiles) {
      const whole = { x: 0, y: 0, w: image.naturalWidth, h: image.naturalHeight }
      return { top: whole, fill: whole }
    }
    const data = this.media.json(ground.tiles)
    return data ? tilesetCells(data) : null
  }

  private paintGround(ground: PlayGround | null, camera: number): void {
    const image = ground ? this.media.image(ground.file) : null
    const cells = ground && image ? this.groundCells(ground, image) : null
    if (!image || !cells) {
      this.placeholder(ground?.name || 'tile', 0, GROUND_Y, { w: PLAY_WIDTH, h: PLAY_HEIGHT - GROUND_Y })
      return
    }
    const size = Math.max(4, cells.top.w)
    for (let x = -(camera % size); x < PLAY_WIDTH; x += size) {
      for (let y = GROUND_Y, row = 0; y < PLAY_HEIGHT; y += size, row += 1) {
        const cell = row === 0 ? cells.top : cells.fill
        this.ctx.drawImage(image, cell.x, cell.y, cell.w, cell.h, x, y, size, size)
      }
    }
  }

  private paintHero(scene: PlayScene, camera: number): void {
    const hero = scene.hero
    const action = heroAction(this.body, this.keys, this.attacking(scene), name => Boolean(hero?.clips[name]))
    if (action !== this.action) {
      this.action = action
      this.actionStart = this.now
    }
    const sprite = hero?.clips[action] || hero?.clips.idle || hero?.sprite || null
    this.drawSprite(sprite, hero?.name || 'hero', this.body.x - camera, this.body.y - 1, this.facingLeft, this.now - this.actionStart, HERO_BOX)
  }

  /** The approved effect plays once per attack, centred on its own pivot in front of the hero. */
  private paintVfx(scene: PlayScene, camera: number): void {
    const vfx = scene.vfx
    const clip = vfx ? this.loadedClip(vfx) : null
    const elapsed = this.now - this.attackStart
    if (!vfx || !clip || elapsed >= clipLength(clip)) return
    this.ctx.save()
    if (vfx.additive) this.ctx.globalCompositeOperation = 'lighter'
    const x = this.body.x - camera + (this.facingLeft ? -28 : 28)
    this.drawSprite(vfx, '', x, this.body.y - 24, this.facingLeft, elapsed, ITEM_BOX)
    this.ctx.restore()
  }

  private attacking(scene: PlayScene): boolean {
    const sprite = scene.hero?.clips.attack
    const clip = sprite ? this.loadedClip(sprite) : null
    return this.now - this.attackStart < (clip ? clipLength(clip) : ATTACK_MS)
  }

  private loadedClip(sprite: PlaySprite): SheetClip | null {
    const image = this.media.image(sprite.file)
    return image ? this.clipFor(sprite, image) : null
  }

  private clipFor(sprite: PlaySprite, image: HTMLImageElement): SheetClip | null {
    if (!sprite.atlas) return stillClip(image.naturalWidth, image.naturalHeight, sprite.anchor)
    const key = `${sprite.atlas}#${sprite.tag}#${sprite.anchor}`
    if (this.clips.has(key)) return this.clips.get(key) ?? null
    const data = this.media.json(sprite.atlas)
    if (data === undefined) return null
    const clip = data ? sheetClip(data, sprite) : null
    this.clips.set(key, clip)
    return clip
  }

  private drawActor(actor: PlayActor, x: number, y: number, flip: boolean, box: Box): void {
    this.drawSprite(actor.sprite, actor.name, x, y, flip, this.now, box)
  }

  /** Draws the frame at ``elapsed`` with its pivot on ``(x, y)``; mirrored only when the sheet allows it. */
  private drawSprite(sprite: PlaySprite | null, name: string, x: number, y: number, flip: boolean, elapsed: number, box: Box): void {
    const clip = sprite ? this.loadedClip(sprite) : null
    const image = sprite && clip ? this.media.image(sprite.file) : null
    if (!image || !clip) {
      this.placeholderAt(name, x, y, box, sprite?.anchor || 'bottom')
      return
    }
    const frame = clip.frames[clipFrameIndex(clip, elapsed)]
    const mirrored = flip && clip.mirror
    const { left, top } = spriteBox(Math.round(x), Math.round(y), clip.pivot, frame.w, mirrored)
    this.ctx.save()
    if (mirrored) {
      this.ctx.translate(left + frame.w, top)
      this.ctx.scale(-1, 1)
      this.ctx.drawImage(image, frame.x, frame.y, frame.w, frame.h, 0, 0, frame.w, frame.h)
    } else {
      this.ctx.drawImage(image, frame.x, frame.y, frame.w, frame.h, left, top, frame.w, frame.h)
    }
    this.ctx.restore()
  }

  private placeholderAt(name: string, x: number, y: number, box: Box, anchor: Anchor): void {
    const top = anchor === 'bottom' ? y - box.h + 1 : y - box.h / 2
    this.placeholder(name, Math.round(x - box.w / 2), Math.round(top), box)
  }

  /** A missing sprite is a named rectangle. */
  private placeholder(name: string, x: number, y: number, box: Box): void {
    if (!name) return
    this.ctx.fillStyle = '#1e293b'
    this.ctx.fillRect(x, y, box.w, box.h)
    this.ctx.fillStyle = '#e8e8ef'
    this.ctx.font = '10px sans-serif'
    this.ctx.fillText(name, x + 2, y + 12, Math.max(8, box.w - 4))
  }
}
