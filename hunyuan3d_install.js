// Optional engine: image-to-3D compiles CUDA extensions (on Windows it needs
// CUDA Toolkit 12.8 and Visual Studio Build Tools), so it is installed on
// request instead of blocking the main Install. Refreshed by Update.
const runtime = require('./runtime_install')
module.exports = {
  requires: {bundle: 'ai'},
  run: [...runtime.preflight('hunyuan3d'), ...runtime.installEngines(['hunyuan3d']), {method: 'script.return', params: {success: true}}]
}
