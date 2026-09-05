import { attachSong, mountSong, trackSong } from './actions'
import type {
  AttachAlternativeSongCommand,
  MountAlternativeSongCommand,
  TrackAlternativeSongCommand,
} from './commands'

export async function attach(command: AttachAlternativeSongCommand) {
  return attachSong(command)
}

export async function mount(command: MountAlternativeSongCommand) {
  return mountSong(command)
}

export async function track(command: TrackAlternativeSongCommand) {
  return trackSong(command)
}
