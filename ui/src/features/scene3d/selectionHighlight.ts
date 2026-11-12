import { BoxHelper, Object3D, type Scene } from 'three'

/** A cyan box on the selection and a paler one on the object under the pointer. */
export function createSelectionHighlight(scene: Scene) {
  const selected = new BoxHelper(new Object3D(), 0x0891b2)
  const hover = new BoxHelper(new Object3D(), 0xa5f3fc)
  selected.visible = false
  hover.visible = false
  scene.add(selected, hover)
  const apply = (helper: BoxHelper, root?: Object3D) => {
    if (!root) { helper.visible = false; return }
    helper.setFromObject(root)
    helper.visible = true
  }
  return {
    sync(selectedRoot?: Object3D, hoverRoot?: Object3D) {
      apply(selected, selectedRoot)
      apply(hover, hoverRoot && hoverRoot !== selectedRoot ? hoverRoot : undefined)
    },
    dispose() {
      scene.remove(selected, hover)
      selected.dispose()
      hover.dispose()
    },
  }
}
