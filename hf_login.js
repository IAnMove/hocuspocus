// Retry the optional Hugging Face login shown during Install.
const runtime = require('./runtime_install')
module.exports = {
  run: [...runtime.hfLogin(), {method: 'script.return', params: {success: true}}],
}
