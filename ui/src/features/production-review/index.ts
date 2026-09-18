export { ProductionReviewDesk } from './ProductionReviewDesk.tsx'
export type { ProductionReviewDeskProps } from './ProductionReviewDesk.tsx'
export { reviewCopy, interpolate, localeKeyParity } from './copy.ts'
export { projectReviewDesk, refreshReviewDesk, shotFromClip, takesForClip, takeRecordFromGeneration, REVIEW_AUTHORITY } from './project.ts'
export { selectExactTake, comparePair, setCompareTake, findShot, findTake, takeIdOf } from './takes.ts'
export { isTakeCompleted, isTakeQueued, canApproveTake, decisionFromTag } from './status.ts'
export { approveShot, rejectShot, setShotNotes, persistCommandsFor } from './decisions.ts'
export { applyPersistCommands, assertRecordProjection } from './persist.ts'
export { planSubsetRegeneration, applyRegenPlan, queuedTakeFromJob, rerunCommands } from './regenerate.ts'
export { exportApprovedSelection } from './exportSelection.ts'
export { productionIdFromActivity, isSameProduction, openReviewFromActivity, activitySourceFromGroup } from './activityOpen.ts'
export { clipRefs } from './refs.ts'
export type {
  ReviewDesk, ReviewShot, ReviewTake, TakeRecord, PipelineLike, PersistCommand,
  RegenPlan, RegenOutcome, ExportSelection, ActivityOpenSource, TakeStatus,
} from './types.ts'
