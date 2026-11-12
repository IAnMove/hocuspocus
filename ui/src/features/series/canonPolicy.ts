import i18n from '../../i18n'

export interface SeriesCanonEpisodeCreateContext {
  createdSeries: boolean
  previousApproval: string
  previousWorldSummary: string
  previousCharacterCount: number
}

export interface SeriesCanonEpisodeCreateDecision {
  approve: boolean
  reason: string
}

/**
 * Creating an episode may prepare a brand-new editable canon base. It must not
 * silently accept pending canon that already belonged to the series.
 */
export function shouldApproveCanonForExplicitEpisodeCreate(
  context: SeriesCanonEpisodeCreateContext,
): SeriesCanonEpisodeCreateDecision {
  if (context.previousApproval === 'approved') {
    return { approve: false, reason: '' }
  }
  const createdNewBase = context.createdSeries
    || (!context.previousWorldSummary.trim() && context.previousCharacterCount === 0)
  if (createdNewBase) {
    return { approve: true, reason: '' }
  }
  return {
    approve: false,
    reason: i18n.t('seriesLab:errors.pendingCanon'),
  }
}
