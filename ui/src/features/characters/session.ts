import type { CharacterKitLibrary } from '../../lib/characterKit'

let characterKitLibrary: CharacterKitLibrary | null = null

export function rememberCharacterKitLibrary(library: CharacterKitLibrary | null): void {
  characterKitLibrary = library
}

export function rememberedCharacterKitLibrary(): CharacterKitLibrary | null {
  return characterKitLibrary
}
