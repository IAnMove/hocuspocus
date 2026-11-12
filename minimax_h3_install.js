// Optional engine: the original ComfyUI workflow for MiniMax H3. Native H3 ships with the base install.
const runtime = require('./runtime_install')
module.exports = {
  requires: {bundle: 'ai'},
  run: [...runtime.preflight('minimax_h3'), ...runtime.installEngines(['minimax_h3']), {method: 'script.return', params: {success: true}}]
}
