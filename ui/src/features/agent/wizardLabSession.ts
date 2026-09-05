export {
  rememberCharacterKitLibrary,
  rememberedCharacterKitLibrary,
} from '../characters/session'

export interface Video3dSessionSnapshot {
  scene_id: string
  title: string
  layers: number
  state: string
}

let video3dScene: Video3dSessionSnapshot | null = null

export function rememberVideo3dScene(scene: Video3dSessionSnapshot | null): void {
  video3dScene = scene
}

export function rememberedVideo3dScene(): Video3dSessionSnapshot | null {
  return video3dScene
}
