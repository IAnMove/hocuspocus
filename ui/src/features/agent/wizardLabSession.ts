import type { CharacterKitLibrary } from '../../lib/characterKit'

export interface Video3dSessionSnapshot {
  scene_id: string
  title: string
  layers: number
  state: string
}

let characterKitLibrary: CharacterKitLibrary | null = null
let video3dScene: Video3dSessionSnapshot | null = null

export function rememberCharacterKitLibrary(library: CharacterKitLibrary | null): void {
  characterKitLibrary = library
}

export function rememberedCharacterKitLibrary(): CharacterKitLibrary | null {
  return characterKitLibrary
}

export function rememberVideo3dScene(scene: Video3dSessionSnapshot | null): void {
  video3dScene = scene
}

export function rememberedVideo3dScene(): Video3dSessionSnapshot | null {
  return video3dScene
}
