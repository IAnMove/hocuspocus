# DEPS-03 vendor revisions

Each optional/native vendor checkout is selected by a full upstream commit
SHA. Install and update both fetch that SHA and use `checkout --detach`; the
per-vendor marker contains the same SHA in both its filename and contents.

| Vendor | Repository | Revision | Evidence |
| --- | --- | --- | --- |
| Hunyuan3D-2 | `Tencent-Hunyuan/Hunyuan3D-2` | `f8db63096c8282cb27354314d896feba5ba6ff8a` | [upstream commit](https://github.com/Tencent-Hunyuan/Hunyuan3D-2/commit/f8db63096c8282cb27354314d896feba5ba6ff8a) |
| Hunyuan3D-2.1 | `Tencent-Hunyuan/Hunyuan3D-2.1` | `82920d643c0dc2f7bfd7255f45f62d386edfe60c` | [upstream commit](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/commit/82920d643c0dc2f7bfd7255f45f62d386edfe60c) |
| SAM3 | `facebookresearch/sam3` | `8f0b7f4d4e7eda2ed606ebde6702c93359ad01da` | [upstream commit](https://github.com/facebookresearch/sam3/commit/8f0b7f4d4e7eda2ed606ebde6702c93359ad01da) |
| UniRig | `VAST-AI-Research/UniRig` | `6793c6640ff01c8fb389f3993434124bb43d2933` | [upstream commit](https://github.com/VAST-AI-Research/UniRig/commit/6793c6640ff01c8fb389f3993434124bb43d2933) |

The shell environment could not run `git ls-remote` during this audit because
DNS resolution for `github.com` was unavailable. The hashes above were not
invented: they were resolved from the upstream GitHub commit-history pages
and commit URLs. A connected install still verifies each SHA through Git's
fetch operation before checkout; if an upstream object is unavailable, the
install fails instead of silently selecting a moving branch head.

The regular Loreframe Lab update only refreshes SAM or UniRig when that optional
environment already exists. Hunyuan3D remains part of the normal install and
update lifecycle. Reset removes the checkout and environment directories, so
stale markers cannot survive a factory reset.
