// Same app-local venv pattern as system/examples/comfy/install.js:50–59.
const runtime = require('./runtime_install')
module.exports = {
  run: [
    {method: 'shell.run', params: {path: 'app', venv: 'env',
      message: runtime.guarded('python -m services.install_speech_tools'),
    }},
    {method: 'script.return', params: {success: true}},
  ],
}
