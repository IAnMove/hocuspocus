// Optional engine: anime face landmarks, CPU only, shared by the menu and Update.
const runtime = require('./runtime_install')
module.exports = {
  requires: {bundle: 'ai'},
  run: [...runtime.preflight('anime_face'), ...runtime.installEngines(['anime_face']), {method: 'script.return', params: {success: true}}]
}
