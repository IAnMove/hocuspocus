export interface CreateVideoEditorProjectCommand {
  projectName: string
}

export interface OpenVideoEditorProjectCommand {
  projectName: string
}

export interface AddVideoEditorClipsCommand {
  outputNames: string[]
}

export interface OrderVideoEditorClipsCommand {
  clipNames: string[]
}

export interface TrimVideoEditorClipCommand {
  clipName: string
  trimStart: number
  trimEnd: number
}

export interface AddVideoEditorAudioCommand {
  clipName: string
  outputName: string
}

export type ValidateVideoEditorTimelineCommand = Record<string, never>

export interface ExportVideoEditorCommand {
  confirm: true
}

export type TrackVideoEditorExportCommand = Record<string, never>
