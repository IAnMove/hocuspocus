# Source-audio lyric timeline

Status: implemented on the feature branch; real-song validation is local evidence
and does not replace CI or review.

## Contract

Music-video analysis produces one source-audio clock before visual planning. When
editable written lyrics are supplied, their literal text is authoritative and
Whisper supplies word boundaries only. The analysis response keeps the raw ASR in
`transcript`, exposes the aligned lines in both `lyrics` and `lyric_timeline`, and
serializes the same cues in `lyrics_srt`.

`lyric_timing` records method, word coverage and approximate-line count. A line
that cannot be supported by recognized words is retained and interpolated between
neighbouring evidence with `source: interpolated` and zero confidence. The UI must
show low coverage rather than present interpolation as exact transcription.

For an unknown uploaded song, the automatic transcript remains the timeline and
the app still emits SRT. Supplying the written lyrics is the path that guarantees
literal text and permits coverage measurement.

## Visual planning

Every planned clip receives the lyric cues that overlap it with absolute times and
clip-relative `offset` values. Semantic entrance, transformation and impact words
also become `visual_events`. The Music Video planner must place the chronological
action at the supplied offset and may build anticipation before it, but it must not
show the result earlier.

The event vocabulary is intentionally small and deterministic. Other story meaning
still comes from the visual planner, which receives every timed lyric line. The
event list does not identify a person from capitalization or invent an asset.

Tagged verse/chorus/bridge boundaries are derived from the first aligned cue in
each section. The section classifier must prefer those audio times over the older
word-count estimate, including Spanish and English section names.

## Validation

- Unit coverage checks literal preservation, quiet-intro transcription options,
  SRT formatting, event anchoring and propagation into clip planning.
- Local acceptance against the three supplied Gandalf tracks aligned 94.5–97.6%
  of written words. For `Gandalf ha entrado al chat`, the line begins at 18.300s
  and the entrance action is anchored to `entrado` at 19.160s.
- This validates timeline construction from existing ASR evidence. It is not a new
  GPU transcription run and does not certify every singer, language or mix.
