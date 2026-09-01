import {
  addAgentVideoEditorAudio,
  addAgentVideoEditorClips,
  createAgentVideoEditorProject,
  exportAgentVideoEditor,
  openAgentVideoEditorProject,
  orderAgentVideoEditorClips,
  trackAgentVideoEditorExport,
  trimAgentVideoEditorClip,
  validateAgentVideoEditorTimeline,
} from './actions'
import type {
  AddVideoEditorAudioCommand,
  AddVideoEditorClipsCommand,
  CreateVideoEditorProjectCommand,
  ExportVideoEditorCommand,
  OpenVideoEditorProjectCommand,
  OrderVideoEditorClipsCommand,
  TrimVideoEditorClipCommand,
} from './commands'

export async function createProject(command: CreateVideoEditorProjectCommand) {
  return createAgentVideoEditorProject(command)
}

export async function openProject(command: OpenVideoEditorProjectCommand) {
  return openAgentVideoEditorProject(command)
}

export async function addClips(command: AddVideoEditorClipsCommand) {
  return addAgentVideoEditorClips(command)
}

export async function orderClips(command: OrderVideoEditorClipsCommand) {
  return orderAgentVideoEditorClips(command)
}

export async function trimClip(command: TrimVideoEditorClipCommand) {
  return trimAgentVideoEditorClip(command)
}

export async function addAudio(command: AddVideoEditorAudioCommand) {
  return addAgentVideoEditorAudio(command)
}

export async function validateTimeline() {
  return validateAgentVideoEditorTimeline()
}

export async function exportProject(command: ExportVideoEditorCommand) {
  return exportAgentVideoEditor(command)
}

export async function trackExport() {
  return trackAgentVideoEditorExport()
}
