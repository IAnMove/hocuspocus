import { MotionLabAudio } from './motionlab/previewAudio'
import { PropLibraryPanel } from './PropLibraryPanel'
import { Scene3DAddPicker } from './Scene3DAddPicker'
import { Scene3DDeskInspector } from './Scene3DDeskInspector'
import { Scene3DDeskOutline } from './Scene3DDeskOutline'
import { Scene3DDeskTopBar } from './Scene3DDeskTopBar'
import { Scene3DDeskViewport } from './Scene3DDeskViewport'
import { Scene3DTransport } from './Scene3DTransport'
import { SceneSpeechAudio } from './speech/preview'
import type { Scene3DDeskModel } from './scene3dDeskModel'
import { Workbench } from '../../components/workbench/Workbench'

/** Vídeo 3D arranged on the shared desk. The desk itself knows nothing about 3D. */
export function Scene3DDesk({ model }: { model: Scene3DDeskModel }) {
  const height = model.fill ? 'flex min-h-0 flex-1 flex-col' : 'flex h-[calc(100dvh-12.5rem)] min-h-[28rem] min-w-0 flex-col'
  return (
    <div data-testid="scene3d-workspace" className={height}>
      <SceneSpeechAudio document={model.sceneDoc} seconds={model.seconds} playing={model.playing && !model.exporting} />
      <MotionLabAudio document={model.sceneDoc} seconds={model.seconds} playing={model.playing && !model.exporting} speed={model.speed} />
      <div className="min-h-0 flex-1">
        <Workbench
          topBar={<Scene3DDeskTopBar model={model} />}
          outline={<Scene3DDeskOutline model={model} />}
          viewport={<Scene3DDeskViewport model={model} />}
          inspector={<Scene3DDeskInspector model={model} />}
          transport={<Scene3DTransport
            playing={model.playing}
            disabled={model.exporting}
            seconds={model.seconds}
            duration={model.sceneDoc.duration}
            speed={model.speed}
            onToggle={model.togglePlay}
            onSeek={model.seek}
            onSpeed={model.onSpeed}
          />}
        />
      </div>
      <Scene3DAddPicker
        open={model.pickerOpen}
        initialCategory={model.pickerCategory}
        disabled={model.editingLocked}
        props={<PropLibraryPanel workspace={model.workspace} disabled={model.editingLocked} onAdd={model.addProp} />}
        onPick={model.onPick}
        onClose={model.closePicker}
      />
      <span data-testid="scene3d-roundtrip" className="hidden">{model.roundtrip ? 'ok' : 'bad'}</span>
    </div>
  )
}
