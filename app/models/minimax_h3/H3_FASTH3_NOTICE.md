# FastVideo FastH3 model notice

Maestro's experimental **FastH3 V2 8-Step** and **FastH3 Trim 8-Step** model
entries are optional text-to-video checkpoints downloaded on demand from
FastVideo (Hao AI Lab). They are MiniMax H3 distilled to eight denoising
evaluations with DMD2 and trained with Video Sparse Attention (VSA). They are
not redistributed in the Maestro source tree.

## Pinned files

| Entry | Repository | Revision | File | Size | SHA-256 |
|---|---|---|---|---|---|
| FastH3 V2 8-Step | `FastVideo/FastVideo-FastH3-Comfy` | `ec1e3aa374a91c57b0b94a1623b7e657c0498cf2` | `diffusion_models/fastvideo_fasth3_8step_v2_pruned_int8_convrot.safetensors` | 22,128,378,696 bytes | `0922785978dc9bfe1adf27d8b291b0ca763f9f165f882e6cb297c72fbb6deda8` |
| FastH3 Trim 8-Step | `FastVideo/FastVideo-FastH3-Trim-Comfy` | `f66c13dc17391dd4da99242a407918b92bf7d5fc` | `diffusion_models/fastvideo_fasth3_trim_8step_int8_convrot.safetensors` | 18,924,757,904 bytes | `ff6e40bc592f7362ea0d7bfcf4e0402bb2c26376d9d1bd4fffb047a5203c2153` |

The SHA-256 values are the Git LFS object ids Hugging Face reports for those
revisions. Both repositories repackage FastVideo's original
`FastVideo/FastVideo-FastH3-8-Step-V2` and `FastVideo/FastVideo-FastH3-Trim-8-Step`
models for ComfyUI.

## What Maestro reuses

Maestro does not download FastVideo's text encoder or VAE copies. These entries
use the same pinned assets as the H3 Fused entries: the Qwen3-VL conditioner
chosen in H3 settings, the INT8 ConvRot video VAE from
`Kijai/MiniMax-H3-experimental` at revision
`a3e7d8da4ae7ba8df0779094cf5ab9d6ee855fe4` (SHA-256
`9bb2d96f218c76babd85e0611b85ca8fb330a90546c01a0005e8a58a59593410`), and the
FP32 audio VAE from `Comfy-Org/MiniMax-H3`. FastVideo's video VAE has the same
tensors and layers; only 35 convolution weights are stored as FP16 there and
as FP32 in the Kijai file.

## Recipe

Eight evaluations, `res_multistep`, video shift 10, audio shift 3, no
classifier-free guidance (guidance 1.0), no stacked LoRAs, no First Block Cache.
Attention is dense by default. Maestro's SLA sparse attention is selectable but
was not part of FastVideo's training, and Maestro does not implement VSA.
Image-to-video and Ref2VA were not distilled, so only text to video (with native
audio) is offered.

The VSA files contain `blocks.N.attn.to_gate_compress` tensors for the
coarse-attention branch. Dense and SLA attention have no such branch, so
Maestro drops these tensors while loading, as FastVideo's own dense backends
ignore them.

## License

Both checkpoints are derivatives of MiniMax H3 and are published under the
[MiniMax H3 Community License Agreement](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE)
(`license: other`). Maestro stores the pinned copy of that license at
`minimax_h3/fasth3/LICENSE` when you download a FastH3 model. The license
applies only within its Applicable Territory: **the European Union, the United
Kingdom, the Republic of Korea and the United States of America are excluded
territories**. It also carries an Acceptable Use Policy and requires modified
files to carry notices and the license to accompany redistributions. Read it
before use. This is not an official MiniMax release.
