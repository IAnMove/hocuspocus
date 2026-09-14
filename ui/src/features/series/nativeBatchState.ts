import { create } from 'zustand'

export const useSeriesNativeBatch = create<{
  running: boolean; stopping: boolean; workspace: string; seriesId: string; episodeId: string
  completed: number; total: number; order: number; phase: string; error: string
}>(() => ({ running: false, stopping: false, workspace: '', seriesId: '', episodeId: '', completed: 0, total: 0, order: 0, phase: '', error: '' }))
