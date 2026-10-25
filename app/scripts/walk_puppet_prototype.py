"""Prototype: a walk cycle made of ONE drawing (so the clothes, hat and bag cannot change between frames).
The contact pose of a character is cut into pieces by See-through (torso, skirt, arms, shins, boots; services/see_through) and the pieces are moved with the joint angles of the walk mould
(services/walk_guides.py). Run from the app folder with its env: python scripts/walk_puppet_prototype.py <layers_dir> <source.png> <out_dir> [frames=12]
Original note: one drawn contact pose, cut into pieces by See-through (torso, skirt, arms, shins, boots) and moved with the joint angles of the walk mould
(services/walk_guides.py: HIP/KNEE/ANKLE curves, arm swing, pelvis bob). Every frame has the same clothes, bag and hat because they are the same pixels.
python puppet_walk.py <layers_dir> <source_keyed.png> <out_dir> [frames=12]"""
import sys, os, json, math
import numpy as np, cv2
from PIL import Image
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from services.walk_guides import curve, HIP_KEYS, KNEE_KEYS, ANKLE_KEYS, ARM_GAIN, walk_pose, THIGH, SHIN, phase_of

def load(path): return np.array(Image.open(path).convert("RGBA"))
def mask_of(a, th=16): return a[..., 3] > th
def comps(mask, min_px=400):
    n, lab, stats, cen = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    out = [(lab == i) for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= min_px]
    return sorted(out, key=lambda m: -int(m.sum()))
def split_two(mask, min_px=400):
    """Two limbs that touch (both arms in one See-through layer): erode until they come apart, then give every pixel to the nearest limb."""
    m8 = mask.astype(np.uint8)
    for r in range(1, 60):
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)); core = cv2.erode(m8, k)
        parts = comps(core > 0, min_px // 4)
        if len(parts) >= 2: break
    else: raise ValueError("the limbs do not come apart")
    seeds = np.zeros(mask.shape, np.int32)
    for i, p in enumerate(parts[:2]): seeds[p] = i + 1
    ws = cv2.watershed(cv2.cvtColor((m8 * 255), cv2.COLOR_GRAY2BGR), seeds.copy())
    return [(ws == 1) & mask, (ws == 2) & mask]
def axis_ends(mask):
    """The two ends of a limb piece along its main axis: (upper end, lower end) as (x, y) of the mean of the extreme 4 % of pixels, and the unit axis from upper to lower."""
    ys, xs = np.nonzero(mask); P = np.column_stack([xs, ys]).astype(float); c = P.mean(0)
    u, s, vt = np.linalg.svd(P - c, full_matrices=False); ax = vt[0]
    if ax[1] < 0: ax = -ax
    t = (P - c) @ ax; lo, hi = np.percentile(t, 3), np.percentile(t, 97)
    top = P[t <= lo].mean(0); bot = P[t >= hi].mean(0)
    return top, bot, ax
def ang(v): return math.atan2(v[0], v[1])          # from straight down, positive toward +x (the way she faces)
def vec(a, l): return np.array([math.sin(a) * l, math.cos(a) * l])
def rot_about(pivot_src, pivot_dst, delta):
    """2x3 affine: rotate by `delta` (same convention as ang) about pivot_src, then place that pivot at pivot_dst."""
    c, s = math.cos(delta), math.sin(delta)
    R = np.array([[c, s], [-s, c]])
    t = np.asarray(pivot_dst) - R @ np.asarray(pivot_src)
    return np.hstack([R, t[:, None]])
def warp_piece(rgba, M, size, upscale=1):
    """Premultiplied warp of an RGBA float image (no dark halo)."""
    a = rgba.astype(np.float32) / 255.0; a[..., :3] *= a[..., 3:4]
    if upscale != 1:
        S = np.diag([upscale, upscale, 1.0]); M3 = np.vstack([M, [0, 0, 1]]); M = (S @ M3)[:2]; size = (size[0] * upscale, size[1] * upscale)
    out = cv2.warpAffine(a, M.astype(np.float32), size, flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    return np.clip(out, 0, 1)
def over(dst, src):
    """premultiplied src over premultiplied dst"""
    return src + dst * (1 - src[..., 3:4])
def piece_rgba(layer, mask=None):
    p = layer.copy()
    if mask is not None: p[..., 3] = np.where(mask, p[..., 3], 0)
    return p
def strip_rgba(shape, a, b, width, colour):
    """A flat limb strip from point a to point b in the limb's colour (RGBA uint8)."""
    strip = np.zeros(shape, np.uint8); ax = (b - a) / max(np.linalg.norm(b - a), 1e-6); n = np.array([-ax[1], ax[0]]) * width / 2
    cv2.fillConvexPoly(strip, np.array([a + n, a - n, b - n, b + n], np.int32), tuple(int(v) for v in colour) + (255,)); return strip
def extend_up(piece, top, ax, width, length, colour):
    """Hidden-under-the-skirt extension: a strip along the limb axis above its upper end, in the limb's own colour."""
    h, w = piece.shape[:2]; strip = np.zeros_like(piece)
    p0 = top - ax * length; p1 = top + ax * 6; n = np.array([-ax[1], ax[0]]) * width / 2
    poly = np.array([p0 + n, p0 - n, p1 - n, p1 + n], np.int32)
    cv2.fillConvexPoly(strip, poly, tuple(int(v) for v in colour) + (255,))
    return _over_u8(strip, piece)
def _over_u8(back, front):
    fa = front[..., 3:4] / 255.0; ba = back[..., 3:4] / 255.0
    oa = fa + ba * (1 - fa); rgb = (front[..., :3] * fa + back[..., :3] * ba * (1 - fa)) / np.maximum(oa, 1e-6)
    return np.dstack([rgb, oa * 255]).astype(np.uint8)
def width_at(mask, point, ax):
    ys, xs = np.nonzero(mask); P = np.column_stack([xs, ys]).astype(float)
    d = (P - point) @ ax; n = np.array([-ax[1], ax[0]]); sel = np.abs(d) < 12
    return float(np.ptp(((P[sel] - point) @ n))) if sel.sum() > 5 else 40.0

def build(layers_dir, src_path, frames=12, up=2, log=print):
    L = {n: load(os.path.join(layers_dir, f"{n}.png")) for n in ("topwear", "bottomwear", "handwear", "legwear", "footwear", "neck", "face", "front_hair", "back_hair", "head", "ears", "nose", "mouth", "eyewhite", "irides", "eyelash", "eyebrow") if os.path.exists(os.path.join(layers_dir, f"{n}.png"))}
    src = load(src_path); H, W = src.shape[:2]
    # ---- the pieces ----
    skirt = L["bottomwear"]; torso = L["topwear"]
    arms = comps(mask_of(L["handwear"])); arms = arms if len(arms) >= 2 else split_two(mask_of(L["handwear"])); legs = comps(mask_of(L["legwear"]), 300); boots = comps(mask_of(L["footwear"]), 600)
    assert len(arms) >= 2 and len(legs) >= 2 and len(boots) >= 2, (len(arms), len(legs), len(boots))
    arms, legs, boots = arms[:2], legs[:2], boots[:2]
    # front = further toward the way she faces (+x) at the contact pose
    arms.sort(key=lambda m: -np.nonzero(m)[1].mean()); legs.sort(key=lambda m: -np.nonzero(m)[1].mean()); boots.sort(key=lambda m: -np.nonzero(m)[1].mean())
    # waist: top of the skirt
    sm = mask_of(skirt); ys, xs = np.nonzero(sm); y0 = ys.min(); top_rows = (ys < y0 + 24); H0 = np.array([xs[top_rows].mean(), y0 + 40.0])
    # the head: every source pixel above the collar; rigid with the torso
    neck_m = mask_of(L["neck"]); cut = int(np.nonzero(neck_m)[0].max() - 6) if neck_m.any() else int(np.nonzero(mask_of(L["head"]))[0].max() + 20)
    cut = min(cut, int(np.nonzero(mask_of(torso))[0].min() + 18))
    head = src.copy(); head[cut:, :, 3] = 0
    # ---- joints of the legs: hem entry (K0), ankle (A0) ----
    leg = []
    for i, (lm, bm) in enumerate(zip(legs, boots)):
        top, bot, ax = axis_ends(lm); btop, bbot, bax = axis_ends(bm)
        K0, A0 = top, bot
        foot_ys, foot_xs = np.nonzero(bm); toe_dir = 1.0 if foot_xs.mean() > bot[0] else -1.0
        leg.append(dict(mask=lm, boot=bm, K0=K0, A0=A0, ax=ax, side="r" if i == 0 else "l", p0=0.0 if i == 0 else 0.5, thigh_len=float(np.linalg.norm(K0 - H0)), shin_len=float(np.linalg.norm(A0 - K0)),
                        thigh_ang=ang(K0 - H0), shin_ang=ang(A0 - K0), boot_piv=btop if btop[1] < bbot[1] else bbot))
    # px per mould metre from the front leg's hip-to-ankle length
    s_px = (leg[0]["thigh_len"] + leg[0]["shin_len"]) / (THIGH + SHIN)
    mould0 = walk_pose(0.0)
    # arms
    arm = []
    for i, am in enumerate(arms):
        top, bot, ax = axis_ends(am); a_top = top; piv = top + ax * 18
        arm.append(dict(mask=am, piv=piv, side="l" if i == 0 else "r", ang0=ang(bot - top), len=float(np.linalg.norm(bot - top))))   # the front arm is the mould's left arm at phase 0
    mean_h = curve(HIP_KEYS, 0.0) / 2 + curve(HIP_KEYS, 0.5) / 2   # as services.walk_guides._arm
    def swing(p_arm): return ARM_GAIN * (curve(HIP_KEYS, (p_arm + 0.5) % 1.0) - mean_h)
    log(f"waist {H0}, cut y {cut}, px per mould m {s_px:.0f}, leg K0 {[tuple(np.round(l['K0'])) for l in leg]} A0 {[tuple(np.round(l['A0'])) for l in leg]}")
    # ---- extended pieces (leg stubs reach up under the skirt) ----
    for l in leg:
        lm = l["mask"]; piece = piece_rgba(L["legwear"], lm); skin = np.median(L["legwear"][lm][:, :3], axis=0)
        wd = width_at(lm, l["K0"] + l["ax"] * 8, l["ax"]); bh = float(np.ptp(np.nonzero(l["boot"])[0])); l["ank_off"] = 0.35 * bh
        l["piece"] = _over_u8(strip_rgba(piece.shape, l["A0"] - l["ax"] * 6, l["A0"] + l["ax"] * (l["ank_off"] + 14), wd * 0.9, skin), piece)   # a stub of leg under the boot
        l["up_w"] = wd; l["skin"] = skin
        l["boot_piece"] = piece_rgba(L["footwear"], l["boot"])
    for a in arm: a["piece"] = piece_rgba(L["handwear"], a["mask"])
    # the shoulder gap: paint the blouse colour where the arm's inpainted shoulder is grey
    # ---- frames ----
    out = []
    ground = max(np.nonzero(l["boot"])[0].max() for l in leg); feet = []
    for k in range(frames):
        phi = phase_of(k, frames) if frames == 12 else k / frames
        pm = walk_pose(phi)
        dy = -(pm["pelvis"][1] - mould0["pelvis"][1]) * s_px; dx = 0.0
        Hk = H0 + np.array([dx, dy])
        feet_low = []; feet_now = {}
        placed = {}
        for l in leg:
            p = (phi + l["p0"]) % 1.0; p0 = l["p0"]
            hip = lambda q: curve(HIP_KEYS, q); knee = lambda q: curve(KNEE_KEYS, q); ank = lambda q: curve(ANKLE_KEYS, q)
            d_hip = math.radians(hip(p) - hip(p0)); d_shin = math.radians((hip(p) - knee(p)) - (hip(p0) - knee(p0))); d_foot = math.radians((hip(p) - knee(p) + ank(p)) - (hip(p0) - knee(p0) + ank(p0)))
            Kk = Hk + vec(l["thigh_ang"] + d_hip, l["thigh_len"]); Ak = Kk + vec(l["shin_ang"] + d_shin, l["shin_len"])
            Ms = rot_about(l["K0"], Kk, d_shin); ank0 = l["A0"] + l["ax"] * l["ank_off"]; ank_k = Ak + vec(l["shin_ang"] + d_shin, l["ank_off"]); Mb = rot_about(ank0, ank_k, d_foot)
            # the thigh strip goes from the hip to the knee: rebuilt for this pose, rotates with nothing else
            thigh = strip_rgba(l["piece"].shape, Hk, Kk, l["up_w"], l["skin"])
            placed[l["side"]] = dict(shin=warp_piece(l["piece"], Ms, (W, H), up), boot=warp_piece(l["boot_piece"], Mb, (W, H), up), thigh=warp_piece(thigh, np.float32([[1, 0, 0], [0, 1, 0]]), (W, H), up), Ak=Ak, Mb=Mb, boot_mask=l["boot"], d_foot=d_foot)
            # lowest boot pixel after the move
            by, bx = np.nonzero(l["boot"]); pts = np.column_stack([bx, by]).astype(float); q = (Mb[:, :2] @ pts.T).T + Mb[:, 2]; feet_low.append(q[:, 1].max()); feet_now[l["side"]] = (float(q[q[:, 1].argmax(), 0]), float(q[:, 1].max()))
        lift = ground - max(feet_low)    # keep the lowest sole on the ground line
        body_M = np.array([[1, 0, dx], [0, 1, dy + lift], [0, 0, 1]])[:2]
        torso_w = warp_piece(torso, body_M, (W, H), up); skirt_w = warp_piece(skirt, body_M, (W, H), up); head_w = warp_piece(head, body_M, (W, H), up)
        arms_w = []
        for a in arm:
            p_arm = (phi + (0.5 if a["side"] == "l" else 0.0)) % 1.0; p_arm0 = 0.5 if a["side"] == "l" else 0.0
            d = math.radians(swing(p_arm) - swing(p_arm0)); Pk = a["piv"] + np.array([dx, dy + lift])
            arms_w.append(warp_piece(a["piece"], rot_about(a["piv"], Pk, d), (W, H), up))
        # compose back to front (far side first): far arm, far leg, near leg, skirt, torso, head, near arm. At phase 0 the mould's left leg/arm are the far ones for a figure facing right.
        far_leg = "l"; near_leg = "r"
        canvas = np.zeros((H * up, W * up, 4), np.float32)
        sh = lambda im: cv2.warpAffine(im, np.float32([[1, 0, 0], [0, 1, lift * up]]), (W * up, H * up))
        # a thigh is only drawn where the skirt hides it: every pixel between the skirt's top and bottom edge in its column
        solid = skirt_w[..., 3] > 0.3; rows = np.arange(solid.shape[0])[:, None]
        top_e = np.where(solid.any(0), solid.argmax(0), 10 ** 9)[None, :]; bot_e = np.where(solid.any(0), solid.shape[0] - 1 - solid[::-1].argmax(0), -1)[None, :]
        span = ((rows >= top_e) & (rows <= bot_e)).astype(np.float32)[..., None]
        order = [arms_w[1]] + [im for side in (far_leg, near_leg) for im in (sh(placed[side]["thigh"]) * span, sh(placed[side]["shin"]), sh(placed[side]["boot"]))] + [skirt_w, torso_w, head_w, arms_w[0]]
        for im in order: canvas = over(canvas, im)
        rgb = canvas[..., :3] / np.maximum(canvas[..., 3:4], 1e-6); frame = np.dstack([np.clip(rgb, 0, 1), canvas[..., 3:4]])
        out.append((frame * 255).astype(np.uint8)); feet.append({side: (x, y + lift) for side, (x, y) in feet_now.items()})
    return out, dict(waist=H0.tolist(), cut=cut, scale=s_px, feet=feet, ground=float(ground))

if __name__ == "__main__":
    layers_dir, src_path, out_dir = sys.argv[1:4]; n = int(sys.argv[4]) if len(sys.argv) > 4 else 12
    os.makedirs(out_dir, exist_ok=True)
    frames, info = build(layers_dir, src_path, n)
    for i, f in enumerate(frames): Image.fromarray(f).save(os.path.join(out_dir, f"puppet_{i:02d}.png"))
    json.dump(info, open(os.path.join(out_dir, "info.json"), "w")); print("frames", len(frames), info)
