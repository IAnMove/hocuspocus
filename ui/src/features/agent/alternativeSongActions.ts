export interface AgentAttachVideoclipAlternativeSongAction {
  type: 'attach_videoclip_alternative_song'
  videoclipName: string
  audioOutputName: string
}

export interface AgentMountVideoclipAlternativeSongAction {
  type: 'mount_videoclip_alternative_song'
  videoclipName: string
  audioOutputName: string
  songId?: string
  confirm: true
}
