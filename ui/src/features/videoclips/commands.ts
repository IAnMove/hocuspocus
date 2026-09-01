export type AttachAlternativeSongCommand = {
  videoclipName: string
  audioOutputName: string
}

export type MountAlternativeSongCommand = {
  videoclipName: string
  audioOutputName: string
  songId?: string
  confirm: true
}

export type TrackAlternativeSongCommand = {
  videoclipName: string
}
