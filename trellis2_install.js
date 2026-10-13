// Optional official 3D engine. Never part of the default Install.
// shell.run + isolated environment: system/examples/wan/install.js:24-30.
const runtime = require('./runtime_install')
module.exports = {
  requires: {bundle: 'ai'},
  run: [...runtime.preflight('trellis2'),
    {method: 'shell.run', params: {message: runtime.guarded('python app/services/trellis2/preflight.py')}},
    ...runtime.installEngines(['trellis2']),
    {method: 'log', params: {raw: 'TRELLIS.2 runtime installed. Restart HocusPocus, enable TRELLIS.2 in Settings > Model Visibility > 3D, then click its download button. Weights are optional and require Hugging Face access to DINOv3 and RMBG-2.0.'}},
    {method: 'script.return', params: {success: true}}],
}
