// A Gaussian-splat set: Spark draws the cloud, and an invisible plane at floorY
// is what the cast stands on. The cloud takes the slot's yaw and scale. The
// floor does not, so it stays horizontal and metric.
// PlaneGeometry faces +Z. rotation.x = -PI/2 sends that normal to +Y
// (a ray straight down hits it). Checked in ui/tests/splatItem.test.tsx.
import { FrontSide, Group, Mesh, MeshBasicMaterial, PlaneGeometry, Vector3, type Object3D, type Scene, type WebGLRenderer } from 'three'
import type { Scene3DSlot } from './types'

export const SPLAT_FLOOR_NAME = 'splat-floor'
export const SPLAT_CLOUD_NAME = 'splat-cloud'
export const SPLAT_FLOOR_SIZE = 40
const FLOOR_LIMIT = 50

export function splatFloorY(slot: Pick<Scene3DSlot, 'splat' | 'position'>): number {
  const raw = slot.splat?.floorY
  return typeof raw === 'number' && Number.isFinite(raw) ? raw : slot.position[1]
}

/** Local Y of the floor when the root sits at slot.position. World Y is then floorY. */
export function splatFloorLocalY(slot: Pick<Scene3DSlot, 'splat' | 'position'>): number {
  return splatFloorY(slot) - slot.position[1]
}

export function studioFloorHiddenForSplat(slots: readonly { media: string }[]): boolean {
  return slots.some(slot => slot.media === 'splat')
}

export function createSplatFloor(): Mesh {
  const mesh = new Mesh(
    new PlaneGeometry(SPLAT_FLOOR_SIZE, SPLAT_FLOOR_SIZE),
    new MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false, colorWrite: false, side: FrontSide }),
  )
  mesh.name = SPLAT_FLOOR_NAME
  mesh.rotation.x = -Math.PI / 2
  // Raycaster skips visible:false. Opacity 0 keeps the plane in the scene and hittable.
  return mesh
}

export function createSplatMount(): Group {
  const root = new Group()
  root.name = 'splat-root'
  const cloud = new Group()
  cloud.name = SPLAT_CLOUD_NAME
  root.add(cloud)
  root.add(createSplatFloor())
  return root
}

export function poseSplatMount(root: Object3D, slot: Scene3DSlot) {
  root.position.set(slot.position[0], slot.position[1], slot.position[2])
  root.rotation.set(0, 0, 0)
  root.scale.set(1, 1, 1)
  const cloud = root.getObjectByName(SPLAT_CLOUD_NAME)
  if (cloud) {
    cloud.rotation.set(0, slot.rotationY, 0)
    cloud.scale.setScalar(Math.max(0.05, slot.scale))
  }
  const floor = root.getObjectByName(SPLAT_FLOOR_NAME)
  if (floor) {
    floor.position.set(0, splatFloorLocalY(slot), 0)
    floor.rotation.set(-Math.PI / 2, 0, 0)
    floor.scale.set(1, 1, 1)
  }
}

/** World +Y of the floor, and its world position. The test's oracle for the mount. */
export function splatFloorWorld(root: Object3D): { y: number; normalY: number } {
  const floor = root.getObjectByName(SPLAT_FLOOR_NAME)
  if (!floor) return { y: Number.NaN, normalY: Number.NaN }
  root.updateMatrixWorld(true)
  const at = new Vector3()
  floor.getWorldPosition(at)
  const normal = new Vector3(0, 0, 1).transformDirection(floor.matrixWorld)
  return { y: at.y, normalY: normal.y }
}

type SparkHost = { scene: Scene; renderer: WebGLRenderer; spark?: Object3D }
const sparkLoads = new WeakMap<SparkHost, Promise<Object3D>>()

function sparkModule() {
  return import('@sparkjsdev/spark')
}

/** One SparkRenderer per world, added to the scene the way Spark renders inside three.js. */
export function ensureSparkRenderer(host: SparkHost): Promise<Object3D> {
  if (host.spark) return Promise.resolve(host.spark)
  const pending = sparkLoads.get(host)
  if (pending) return pending
  const job = sparkModule().then(({ SparkRenderer }) => {
    if (host.spark) return host.spark
    const spark = new SparkRenderer({ renderer: host.renderer })
    host.scene.add(spark)
    host.spark = spark
    return spark
  })
  sparkLoads.set(host, job)
  return job
}

export async function loadSplatCloud(url: string): Promise<Object3D> {
  const { SplatMesh } = await sparkModule()
  const mesh = new SplatMesh({ url })
  await mesh.initialized
  mesh.name = 'splat-mesh'
  return mesh
}

export function releaseSpark(host: { spark?: Object3D }) {
  const spark = host.spark
  if (!spark) return
  spark.removeFromParent()
  const dispose = (spark as { dispose?: () => void }).dispose
  if (typeof dispose === 'function') dispose.call(spark)
  host.spark = undefined
}

export function parseSplatFloor(value: unknown): { floorY: number } {
  const raw = value && typeof value === 'object' ? Number((value as { floorY?: unknown }).floorY) : Number.NaN
  const floorY = Number.isFinite(raw) ? Math.min(FLOOR_LIMIT, Math.max(-FLOOR_LIMIT, raw)) : 0
  return { floorY }
}
