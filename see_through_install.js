// Optional engine: isolated recipe, shared by the menu and Update.
const runtime = require('./runtime_install')
module.exports = {
  requires: {bundle: 'ai'},
  run: [...runtime.preflight('see_through'), ...runtime.installEngines(['see_through']), {method: 'script.return', params: {success: true}}]
}
