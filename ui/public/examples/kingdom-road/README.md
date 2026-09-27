# Kingdom Road

Open `/examples/kingdom-road/` on a running HocusPocus installation.

- **Calzada infinita**: 224 seconds, 35 animated backgrounds, continuous downhill road and transparent skater.
- **El jinete PSX**: 168 seconds, the same 35 backgrounds, selective PSX treatment of knight and dragon.
- **Que tú veas el alba**: a Spanish YuE2 song and vertical music film. Forty template compositions, the two new journey treatments and story scenes follow the native audio analysis. The knight rescues the princess and dies content that she lives.

The page provides MP4 downloads, the song, optional Spanish subtitles, ratings stored in the browser, and two archives containing 35 editable World3D documents each. Open individual documents through **Studios → Video 3D → Load shot**. They reference assets already shipped in the linked example collections; these JSON archives do not duplicate the source media.

## Reproduce through the application

All media processing uses HocusPocus: MiniMax image jobs, H3 Fused motion, existing RIFE and background-removal assets, the native World3D renderer, YuE2 generation, audio analysis and Video Editor assembly. The plans and publication records describe the source assets and timings. No external compositor supplies the finished media.

- `skate-long-plan.json` and `dragon-long-plan.json`: complete scene documents in shot order.
- `music-edit-plan.json`: actual detected beat boundaries and frame-rounded edit decisions.
- `alba.editor-request.json`: native Video Editor export request.
- `RENDERS.json`: final output properties and native publication evidence.

Native API examples (same origin; set `base` / `BASE_URL` to your installation):

```javascript
const plan = await fetch(`${base}/examples/kingdom-road/alba.editor-request.json`).then(r => r.json());
const job = await fetch(`${base}/api/v1/video-editor/export`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(plan),
}).then(r => r.json());
// Poll GET /api/v1/video-editor/export/{job.job_id}.
```

```python
import requests
plan = requests.get(BASE_URL + '/examples/kingdom-road/alba.editor-request.json').json()
job = requests.post(BASE_URL + '/api/v1/video-editor/export', json=plan).json()
```

```bash
curl "$BASE_URL/examples/kingdom-road/alba.editor-request.json" -o edit.json
curl -H 'Content-Type: application/json' --data-binary @edit.json "$BASE_URL/api/v1/video-editor/export"
```

The assembly request references this production's workspace assets. On another installation, import its source clips and update those references before submitting it. The bundled MP4s are portable. The long skater review is 540×960 to fit the repository file limit; its 720×1280 master stays in the app gallery and has a separate download link on this installation. Editable scene exports retain their original 720×1280 resolution.

## Continuity controls

**Video → Continuity between shots** exposes an optional source interval, forward/backward looping and elapsed sequence time. A source interval can avoid a poor section of a generated matte. Forward/backward loops reverse the movement on alternate passes; choose that deliberately. Existing scenes retain normal forward playback.

The native exporter tries hardware WebGL on Linux and falls back to software rendering. It shares the local GPU queue with generation jobs. A bounded, workspace-local all-intra cache speeds deterministic video seeks and preserves VP9 alpha; it never modifies original media or fetches remote URLs. Cache failure uses the original asset.

YuE2 now publishes audio metadata with the standard family-handler signature and reuses an installed model precision when the preferred one is absent. This avoids downloading another multi-gigabyte variant merely because global precision differs.
