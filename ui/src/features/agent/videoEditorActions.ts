export {
  addAgentVideoEditorAudio,
  addAgentVideoEditorClips,
  createAgentVideoEditorProject,
  exportAgentVideoEditor,
  openAgentVideoEditorProject,
  orderAgentVideoEditorClips,
  trackAgentVideoEditorExport,
  trimAgentVideoEditorClip,
  validateAgentVideoEditorTimeline,
} from '../video-editor/actions'

export interface AgentCreateVideoEditorProjectAction {
  type: 'create_video_editor_project'
  projectName: string
}

export interface AgentOpenVideoEditorProjectAction {
  type: 'open_video_editor_project'
  projectName: string
}

export interface AgentAddVideoEditorClipsAction {
  type: 'add_video_editor_clips'
  outputNames: string[]
}

export interface AgentOrderVideoEditorClipsAction {
  type: 'order_video_editor_clips'
  clipNames: string[]
}

export interface AgentTrimVideoEditorClipAction {
  type: 'trim_video_editor_clip'
  clipName: string
  trimStart: number
  trimEnd: number
}

export interface AgentAddVideoEditorAudioAction {
  type: 'add_video_editor_audio'
  clipName: string
  outputName: string
}

export interface AgentValidateVideoEditorTimelineAction {
  type: 'validate_video_editor_timeline'
}

export interface AgentExportVideoEditorAction {
  type: 'export_video_editor'
  confirm: true
}

export interface AgentTrackVideoEditorExportAction {
  type: 'track_video_editor_export'
}
