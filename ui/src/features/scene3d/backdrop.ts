import type { Scene3DLoop, Scene3DSlot } from './types.ts'
import { mediaScreenMountKey } from './mediaScreen.ts'

export function wrapUnit(value: number): number {
  if (!Number.isFinite(value)) return 0
  return ((value % 1) + 1) % 1
}

export function cylinderUvOffset(sceneSeconds: number, speed: number): number {
  const safeSpeed = Number.isFinite(speed) ? speed : 0
  const time = Number.isFinite(sceneSeconds) ? sceneSeconds : 0
  return wrapUnit(time * safeSpeed)
}

export function parseScene3DLoop(raw: unknown): Scene3DLoop | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as { cylinder?: unknown; speed?: unknown }
  const speed = Number(value.speed)
  return {
    cylinder: value.cylinder === true,
    speed: Number.isFinite(speed) ? speed : 0,
  }
}

export function isImageBackdrop(slot: Pick<Scene3DSlot, 'media'>): boolean {
  return slot.media === 'image'
}

export function isCylinderBackdrop(slot: Pick<Scene3DSlot, 'media' | 'loop' | 'surface'>): boolean {
  return slot.media === 'image' && slot.surface !== 'floor' && slot.surface !== 'environment' && slot.loop?.cylinder === true
}

export function slotMountKey(slot: Pick<Scene3DSlot, 'sourceUrl' | 'media' | 'loop' | 'surface' | 'textureRepeat' | 'screen'>): string {
  if (slot.media !== 'image') return `${slot.sourceUrl}\0${slot.media}\0${mediaScreenMountKey(slot.screen)}`
  return `${slot.sourceUrl}\0${isCylinderBackdrop(slot) ? 'cyl' : 'plane'}\0${slot.surface ?? ''}\0${slot.textureRepeat ?? ''}`
}
