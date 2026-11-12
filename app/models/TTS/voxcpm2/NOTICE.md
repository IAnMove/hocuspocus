# VoxCPM2 inference code

Vendored from the `voxcpm` Python package **2.0.3** (OpenBMB, Apache-2.0, see `LICENSE`):
<https://github.com/OpenBMB/VoxCPM>, <https://pypi.org/project/voxcpm/2.0.3/>.

Only the VoxCPM2 inference path is kept: `model/voxcpm2.py`, `model/utils.py` and the
`modules/` it imports. Left out: the VoxCPM 1.x model, `core.py` (replaced by
`../voxcpm2_handler.py` and `pipeline.py`), the CLI, training, the ModelScope
ZipEnhancer denoiser and the text normaliser (`inflect`/`wetext`), so the package's
gradio, funasr, modelscope and datasets requirements are not needed.

Changes to the vendored files:
- `modules/locdit/unified_cfm.py`: the v1 `VoxCPMLocDiT` import (a type hint) points at
  `local_dit_v2`.
- `model/voxcpm2.py` `_inference`: an optional `_step_hook(step, max_steps)` is called after
  each step for WanGP progress, early stop (returns True) and abort (raises); tqdm is off
  when it is set.
- `model/__init__.py`, `modules/*/__init__.py`: export the v2 classes only.

Weights: `openbmb/VoxCPM2` on Hugging Face, pinned in `../voxcpm2_handler.py`.
