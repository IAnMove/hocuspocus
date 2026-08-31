import assert from 'node:assert/strict'
import test from 'node:test'

test('named film and series looks require MiniMax H3 text-to-video', async () => {
  const {
    namedFilmOrSeriesLook,
    musicVideoShouldUseDirectVideo,
    applyMusicVideoDirectVideoDefaults,
    inferStoryProjectTypeFromText,
    resolveMusicVideoVisualStyle,
  } = await import('../src/features/stories/musicVideoLook.ts')
  const { createStoryProject } = await import('../src/features/stories/model.ts')

  assert.equal(namedFilmOrSeriesLook('Classic adult animated style of Heavy Metal 1981'), true)
  assert.equal(namedFilmOrSeriesLook('cinematic neon rain, wet asphalt, no named work'), false)
  assert.equal(inferStoryProjectTypeFromText('Crea un videoclip llamado El Himno'), 'music_video')

  const project = createStoryProject('music_video')
  project.visualStyle = 'animación adulta fantástica de la película Heavy Metal 1981'
  project.musicVideoGenerationMode = 'image_guided'
  assert.equal(musicVideoShouldUseDirectVideo(project), true)
  const next = applyMusicVideoDirectVideoDefaults(project)
  assert.equal(next.musicVideoGenerationMode, 'direct_video')
  assert.equal(next.protagonistConsistency, false)
  assert.match(next.directVideoMasterPrompt, /text-to-video/i)

  const brief = 'Videoclip heavy metal con estética visual de animación adulta fantástica de la película Heavy Metal 1981.'
  const recoveredStyle = resolveMusicVideoVisualStyle(
    'music_video',
    'Dirección visual cinematográfica coherente, personajes legibles y continuidad entre escenas.',
    brief,
  )
  assert.equal(recoveredStyle, brief)
  const recovered = applyMusicVideoDirectVideoDefaults({
    ...createStoryProject('music_video'),
    visualStyle: recoveredStyle,
    characterVisualStyle: recoveredStyle,
    musicVideoGenerationMode: 'image_guided',
  })
  assert.match(recovered.directVideoMasterPrompt, /Heavy Metal 1981/i)
})
