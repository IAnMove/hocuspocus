import { type RefObject } from 'react'
import { StoryAssetsImporter } from './StoryAssetsImporter'
import { StoryAssetsLibrary } from './StoryAssetsLibrary'
import { StoryAssetsStyleConverter } from './StoryAssetsStyleConverter'
import type { PendingSmartAsset } from './storyLabAssets'
import type { StoryProject, StoryVisualAsset } from './types'
import type { ModelDef } from '../../types'

export function StoryAssetsTab(props: {
  project: StoryProject
  smartAssetBusy: boolean
  smartAssetDescription: string
  setSmartAssetDescription: (value: string) => void
  smartAssetRef: RefObject<HTMLInputElement | null>
  pendingSmartAssets: PendingSmartAsset[]
  setPendingSmartAssets: (value: PendingSmartAsset[]) => void
  analyzeSmartAssets: (files: File[]) => void
  applySmartAssets: () => void
  patchPendingSmartAsset: (index: number, patch: Partial<PendingSmartAsset>) => void
  styleConversion: string
  setStyleConversion: (value: string) => void
  styleConversionModel: string
  setStyleConversionModel: (value: string) => void
  styleConversionBusy: boolean
  styleModelDownloading: string
  setStyleModelDownloadError: (value: string) => void
  styleModelDownloadError: string
  localStyleModels: ModelDef[]
  qwenModel: string
  fluxModel: string
  styleAssetIds: string[]
  setStyleAssetIds: (ids: string[]) => void
  styleUsesMiniMax: boolean
  selectedStyleModel?: ModelDef
  styleModelReady: boolean
  miniMaxIncompatibleSelection: boolean
  installStyleConversionModel: () => void
  cancelStyleConversion: () => void
  convertSelectedAssetsToStyle: () => void
  selectedDraftAssetIds: string[]
  deleteSelectedDraftAssets: () => void
  toggleStyleAsset: (id: string) => void
  patchVisualAsset: (id: string, patch: Partial<StoryVisualAsset>) => void
  visualAssetsNewestFirst: StoryVisualAsset[]
}) {
  return (
    <>
      <StoryAssetsImporter
        project={props.project}
        smartAssetBusy={props.smartAssetBusy}
        smartAssetDescription={props.smartAssetDescription}
        setSmartAssetDescription={props.setSmartAssetDescription}
        smartAssetRef={props.smartAssetRef}
        pendingSmartAssets={props.pendingSmartAssets}
        setPendingSmartAssets={props.setPendingSmartAssets}
        analyzeSmartAssets={props.analyzeSmartAssets}
        applySmartAssets={props.applySmartAssets}
        patchPendingSmartAsset={props.patchPendingSmartAsset}
      />
      <StoryAssetsStyleConverter
        styleConversion={props.styleConversion}
        setStyleConversion={props.setStyleConversion}
        styleConversionModel={props.styleConversionModel}
        setStyleConversionModel={props.setStyleConversionModel}
        styleConversionBusy={props.styleConversionBusy}
        styleModelDownloading={props.styleModelDownloading}
        setStyleModelDownloadError={props.setStyleModelDownloadError}
        styleModelDownloadError={props.styleModelDownloadError}
        localStyleModels={props.localStyleModels}
        qwenModel={props.qwenModel}
        fluxModel={props.fluxModel}
        styleAssetIds={props.styleAssetIds}
        styleUsesMiniMax={props.styleUsesMiniMax}
        selectedStyleModel={props.selectedStyleModel}
        styleModelReady={props.styleModelReady}
        miniMaxIncompatibleSelection={props.miniMaxIncompatibleSelection}
        installStyleConversionModel={props.installStyleConversionModel}
        cancelStyleConversion={props.cancelStyleConversion}
        convertSelectedAssetsToStyle={props.convertSelectedAssetsToStyle}
      />
      <StoryAssetsLibrary
        project={props.project}
        styleAssetIds={props.styleAssetIds}
        setStyleAssetIds={props.setStyleAssetIds}
        selectedDraftAssetIds={props.selectedDraftAssetIds}
        styleConversionBusy={props.styleConversionBusy}
        deleteSelectedDraftAssets={props.deleteSelectedDraftAssets}
        toggleStyleAsset={props.toggleStyleAsset}
        patchVisualAsset={props.patchVisualAsset}
        visualAssetsNewestFirst={props.visualAssetsNewestFirst}
      />
    </>
  )
}
