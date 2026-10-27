import type { Dispatch, MutableRefObject, ReactNode, SetStateAction } from 'react'
import type { ApiOutput } from '../../api/client'
import type { ExportReviewInput } from '../render/exportReview'
import type { RenderChoice } from '../render/renderEstimate'
import type { AddPickerCategory, AddPickerItem } from './addPickerCatalog'
import type { Scene3DDocumentRef, Scene3DHistorySession } from './documentHistory'
import type { Scene3DStageHandle } from './Scene3DStage'
import type { LibraryProp } from './propLibrary'
import type { SlotSourceCapture, SlotSourceLive } from './slotSource'
import type { Scene3DTemplateId } from './templates'
import type { Scene3DClipCatalogEntry, Scene3DDocument, Scene3DSlot } from './types'
import type { TransformMode } from './transformGizmo'
import type { World3DUserTemplate } from './userTemplates'

export type WalkBakeControl = { sceneDuration: number; baking: boolean; error?: string; onBake: () => void }

/** Values and handlers the desk layout reads. The workspace owns the state. */
export type Scene3DDeskModel = {
  fill: boolean
  topBarExtra?: ReactNode
  sceneDoc: Scene3DDocument
  editingLocked: boolean
  exporting: boolean
  playing: boolean
  selected?: Scene3DSlot
  selectedId: string
  selectedWorldSfxId?: string
  speechVisible: boolean
  speechOpen: boolean
  pickTarget?: string
  generation: number
  transformMode: TransformMode
  seconds: number
  speed: number
  fps: number
  count: number
  workspace: string
  session: Scene3DHistorySession
  stageRef: MutableRefObject<Scene3DStageHandle | null>
  catalogs: Record<string, Scene3DClipCatalogEntry[]>
  modelItems: ApiOutput[]
  imageItems: ApiOutput[]
  videoItems: ApiOutput[]
  screenTargets: Record<string, { meshes: string[]; nodes: string[] }>
  keepAssets: boolean
  selectedUserTemplateId?: string
  clipIssue: string | null
  exportNote: string | null
  receiptReview: ExportReviewInput | null
  roundtrip: boolean
  pickerOpen: boolean
  pickerCategory: AddPickerCategory
  setKeepAssets: (value: boolean) => void
  mountTemplate: (id: Scene3DTemplateId) => void
  mountUserTemplate: (pack: World3DUserTemplate) => void
  applyScene: (updater: Scene3DDocument | ((current: Scene3DDocument) => Scene3DDocument), group?: string) => void
  loadDocument: (next: Scene3DDocument, source?: Scene3DDocumentRef) => void
  acknowledgeSave: (output: ApiOutput, document: Scene3DDocument, identity: Scene3DDocumentRef) => void
  selectSlot: (id: string) => void
  setTransformMode: Dispatch<SetStateAction<TransformMode>>
  setPlaying: Dispatch<SetStateAction<boolean>>
  setFrame: Dispatch<SetStateAction<number>>
  setPickTarget: Dispatch<SetStateAction<string | undefined>>
  setSelectedWorldSfxId: Dispatch<SetStateAction<string | undefined>>
  setCatalogs: Dispatch<SetStateAction<Record<string, Scene3DClipCatalogEntry[]>>>
  setScreenTargets: Dispatch<SetStateAction<Record<string, { meshes: string[]; nodes: string[] }>>>
  setSpeechOpen: Dispatch<SetStateAction<boolean>>
  exportScene: () => void
  abortExport: () => void
  assignChoice: (slot: Scene3DSlot, capture: SlotSourceCapture, item: ApiOutput | null) => void
  bumpGeneration: () => void
  onExamplesInstalled: () => void
  liveSource: () => SlotSourceLive
  walkFor: (slot: Scene3DSlot) => WalkBakeControl
  onPick: (item: AddPickerItem) => void
  openPicker: (category: AddPickerCategory) => void
  closePicker: () => void
  addProp: (prop: LibraryProp) => void
  addScreen: () => void
  removeSelected: () => void
  resetSelectedPose: () => void
  onStageSelect: (id: string) => void
  onDemo: (id: 'depth' | 'duel' | 'mixed') => void
  onShowcase: (collection?: 'all' | 'anime' | 'retro') => void
  seek: (time: number) => void
  setRenderChoice: (choice: RenderChoice) => void
  onSpeed: (speed: number) => void
  togglePlay: () => void
  restorePreviousShot: () => void
  preview: () => string | undefined
}
