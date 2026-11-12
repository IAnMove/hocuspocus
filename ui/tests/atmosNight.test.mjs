import assert from 'node:assert/strict'
import test from 'node:test'
import { Color } from 'three'
import { NIGHT, effectivePalette, isNight } from '../src/features/scene3d/atmos/night.ts'
import { parseAtmosSettings, resolveAtmos } from '../src/features/scene3d/atmos/params.ts'
import { buildMeadow } from '../src/features/scene3d/atmos/sets/meadow.ts'
import { buildClearing } from '../src/features/scene3d/atmos/sets/clearing.ts'

const resolved = (set, patch) => resolveAtmos(parseAtmosSettings(patch, set), 'low', set)

test('night is a time of day of the meadow and the clearing and it paints the night palette whatever palette is named', () => {
  assert.equal(isNight('night'), true)
  assert.equal(isNight('spring'), false)
  assert.equal(effectivePalette({ palette: 'clover', timeOfDay: 'night' }), 'night')
  assert.equal(effectivePalette({ palette: 'clover', timeOfDay: 'spring' }), 'clover')
  for (const [set, palette, time] of [['atmos-meadow', 'clover', 'night'], ['atmos-clearing', 'green', 'night']]) {
    const night = resolved(set, { palette, timeOfDay: time })
    assert.equal(night.timeOfDay, 'night')
    assert.equal(night.palette, 'night')
    assert.ok(new Color(night.fogColor).getHex() === new Color(NIGHT.horizon).getHex(), `${set} fog is the night horizon`)
    assert.ok(night.sun[1] < 0, 'the moon light comes from above')
  }
  assert.equal(resolved('atmos-meadow', { palette: 'clover', timeOfDay: 'spring' }).palette, 'clover')
  assert.notEqual(resolved('atmos-meadow', { palette: 'clover', timeOfDay: 'spring' }).fogColor, NIGHT.horizon)
})

test('a night world carries stars and a moon in the sky, a day world does not', () => {
  const night = buildMeadow(resolved('atmos-meadow', { palette: 'clover', timeOfDay: 'night' }), true)
  const sky = night.root.getObjectByName('atmos-night-sky')
  assert.ok(sky, 'night sky group')
  assert.equal(sky.children.filter(child => child.name === 'atmos-stars').length, 2)
  const moon = sky.getObjectByName('atmos-moon')
  assert.ok(moon && moon.position.y > 0, 'the moon is above the horizon')
  assert.equal(moon.material.fog, false, 'sky bodies ignore the fog')
  night.handle.dispose()
  const day = buildMeadow(resolved('atmos-meadow', { palette: 'clover', timeOfDay: 'spring' }), true)
  assert.equal(day.root.getObjectByName('atmos-night-sky'), undefined)
  day.handle.dispose()
})

test('the night grass is dark and the clearing forest drops its self-glow', () => {
  const night = buildMeadow(resolved('atmos-meadow', { palette: 'clover', timeOfDay: 'night' }), true)
  const grass = night.root.getObjectByName('atmos-grass')
  assert.ok(new Color(grass.material.uniforms.uTip.value).getHSL({}).l < 0.3, 'tips are dark at night')
  night.handle.dispose()
  const dayClearing = buildClearing(resolved('atmos-clearing', { palette: 'green', timeOfDay: 'golden' }), true)
  const nightClearing = buildClearing(resolved('atmos-clearing', { palette: 'green', timeOfDay: 'night' }), true)
  const glow = root => { let sum = 0; root.traverse(o => { const m = o.material; if (m && m.emissiveIntensity !== undefined) sum += m.emissiveIntensity }); return sum }
  assert.ok(glow(nightClearing.root) < glow(dayClearing.root) * 0.5)
  dayClearing.handle.dispose()
  nightClearing.handle.dispose()
})

test('the meadow has a dawn, thins its clouds with the motes setting and the night clearing drops the falling leaf', () => {
  const dawn = resolved('atmos-meadow', { palette: 'hay', timeOfDay: 'dawn' })
  assert.equal(dawn.timeOfDay, 'dawn')
  assert.equal(dawn.palette, 'hay')
  const clouds = patch => { const built = buildMeadow(resolved('atmos-meadow', { palette: 'clover', timeOfDay: 'spring', ...patch }), true); const mesh = built.root.getObjectByName('atmos-cloud'); const count = mesh ? mesh.count : 0; built.handle.dispose(); return count }
  assert.ok(clouds({}) > 0, 'the default keeps its clouds')
  assert.equal(clouds({ motes: 0 }), 0, 'motes 0 is a clear sky')
  assert.ok(clouds({ motes: 0.1 }) < clouds({}), 'fewer motes, fewer clouds')
  const nightClearing = buildClearing(resolved('atmos-clearing', { palette: 'green', timeOfDay: 'night' }), true)
  const dayClearing = buildClearing(resolved('atmos-clearing', { palette: 'green', timeOfDay: 'golden' }), true)
  assert.equal(nightClearing.root.getObjectByName('atmos-fall'), undefined)
  assert.ok(dayClearing.root.getObjectByName('atmos-fall'))
  nightClearing.handle.dispose()
  dayClearing.handle.dispose()
})
