"""Generate poster assets: SDG tiles, architecture diagram, result charts, screenshot triptych."""
import os, json
from PIL import Image, ImageDraw, ImageFont
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

# Every path below was hardcoded to a sandbox that exists on no machine this
# repo runs on, so the script could not regenerate the poster anywhere.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get("POSTER_ASSETS_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets"))
os.makedirs(OUT, exist_ok=True)

def _find_font(candidates):
    """First font file that exists, so this runs off a Linux box too.

    matplotlib ships DejaVu, which is the last candidate: it is always present
    wherever this script's other import already is, so there is no arrangement
    in which the search comes up empty.
    """
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return os.path.join(os.path.dirname(matplotlib.__file__),
                        "mpl-data", "fonts", "ttf", "DejaVuSans.ttf")


DJV_B = _find_font([
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    os.path.join(os.path.dirname(matplotlib.__file__),
                 "mpl-data", "fonts", "ttf", "DejaVuSans-Bold.ttf"),
])
DJV_R = _find_font([
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
])

NAVY = "#10294A"

# ---------------------------------------------------------------- SDG tiles
def sdg_tile(num, title, color, glyph, path, size=900):
    im = Image.new("RGB", (size, size), color)
    d = ImageDraw.Draw(im)
    m = int(size * 0.075)
    fnum = ImageFont.truetype(DJV_B, int(size * 0.185))
    d.text((m, m - int(size * 0.02)), str(num), font=fnum, fill="white")

    # title, wrapped
    words = title.split()
    ftit = ImageFont.truetype(DJV_B, int(size * 0.082))
    lines, cur = [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=ftit) > size - 2 * m and cur:
            lines.append(cur); cur = w
        else:
            cur = t
    lines.append(cur)
    y = m + int(size * 0.20)
    for ln in lines:
        d.text((m, y), ln, font=ftit, fill="white")
        y += int(size * 0.097)

    glyph(d, size, m)
    im.save(path)

def g4(d, s, m):  # book + pencil
    cx, cy = s * 0.52, s * 0.775
    w, h = s * 0.36, s * 0.16
    d.polygon([(cx - w, cy), (cx - w * 0.05, cy - h * 0.55), (cx - w * 0.05, cy + h * 0.45), (cx - w, cy + h)],
              fill="white")
    d.polygon([(cx + w, cy), (cx + w * 0.05, cy - h * 0.55), (cx + w * 0.05, cy + h * 0.45), (cx + w, cy + h)],
              fill="white")
    # graduation cap above
    gx, gy = cx, cy - h * 1.5
    d.polygon([(gx, gy - s * 0.075), (gx + s * 0.16, gy), (gx, gy + s * 0.075), (gx - s * 0.16, gy)], fill="white")
    d.rectangle([gx + s * 0.135, gy, gx + s * 0.152, gy + s * 0.085], fill="white")

def g9(d, s, m):  # bars + gear-ish nodes
    base = s * 0.90
    xs = [0.30, 0.46, 0.62]
    hs = [0.11, 0.18, 0.26]
    for x, h in zip(xs, hs):
        d.rectangle([s * x, base - s * h, s * (x + 0.11), base], fill="white")
    # connecting nodes
    pts = [(s * 0.355, base - s * 0.155), (s * 0.515, base - s * 0.225), (s * 0.675, base - s * 0.305)]
    for i in range(len(pts) - 1):
        d.line([pts[i], pts[i + 1]], fill="white", width=int(s * 0.016))
    for p in pts:
        r = s * 0.032
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill="white")

def g10(d, s, m):  # equals sign with arrows
    cx, cy = s * 0.52, s * 0.78
    d.rectangle([cx - s * 0.15, cy - s * 0.055, cx + s * 0.15, cy - s * 0.015], fill="white")
    d.rectangle([cx - s * 0.15, cy + s * 0.015, cx + s * 0.15, cy + s * 0.055], fill="white")
    for sx in (-1, 1):
        tipx = cx + sx * s * 0.30
        d.polygon([(tipx, cy), (tipx - sx * s * 0.075, cy - s * 0.075), (tipx - sx * s * 0.075, cy + s * 0.075)],
                  fill="white")

sdg_tile(4, "QUALITY EDUCATION", "#C5192D", g4, f"{OUT}/sdg04.png")
sdg_tile(9, "INDUSTRY, INNOVATION AND INFRASTRUCTURE", "#FD6925", g9, f"{OUT}/sdg09.png")
sdg_tile(10, "REDUCED INEQUALITIES", "#DD1367", g10, f"{OUT}/sdg10.png")
print("sdg tiles ok")

# ------------------------------------------------------- architecture diagram
fig, ax = plt.subplots(figsize=(6.6, 5.35), dpi=200)
ax.set_xlim(0, 100); ax.set_ylim(15.4, 96.5); ax.axis("off")

def box(x, y, w, h, text, fc, ec, tc="white", fs=8.2, weight="bold", r=1.6):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
                                fc=fc, ec=ec, lw=1.1, zorder=2))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs,
            color=tc, fontweight=weight, zorder=3, linespacing=1.35)

def arrow(x, y0, y1, lw=2.0):
    ax.annotate("", xy=(x, y1), xytext=(x, y0),
                arrowprops=dict(arrowstyle="-|>", color=NAVY, lw=lw, mutation_scale=16), zorder=1)

ACC = "#F2F5F9"; BOR = "#C7D0DC"; ORG = "#FD6925"

y = 88.0
box(2, y, 29.5, 6.6, "Browser / CI", "#2E5C8A", "#2E5C8A", fs=13)
box(35.2, y, 29.5, 6.6, "Playwright SDK", "#2E5C8A", "#2E5C8A", fs=13)
box(68.4, y, 29.5, 6.6, "CLI", "#2E5C8A", "#2E5C8A", fs=13)
for cx in (16.75, 49.95, 83.15):
    ax.annotate("", xy=(cx, 85.6), xytext=(cx, 87.6),
                arrowprops=dict(arrowstyle="-|>", color=NAVY, lw=1.8, mutation_scale=14), zorder=1)

box(2, 78.4, 96, 7.0, "FastAPI server  ·  auth + RBAC  ·  REST API  ·  live updates",
    NAVY, NAVY, fs=12.0, weight="normal")
arrow(50, 78.0, 75.6, lw=2.0)

stages = [
    ("1  CAPTURE", "fixed viewport, locale, timezone, device; DOM sidecar"),
    ("2  NORMALISE", "pad to common bounds, each with its own background"),
    ("3  PIXEL DIFF", "delta → regions → merge; mismatch %, SSIM, boxes"),
    ("4  CLASSIFY", "ResNet50 Siamese + rule features + DOM evidence"),
    ("5  DECIDE", "pass / fail / review + severity; DOM overrides noise floor"),
]
y = 74.6
Hh = 6.6
for i, (head, body) in enumerate(stages):
    ax.add_patch(FancyBboxPatch((2, y - Hh), 96, Hh, boxstyle="round,pad=0,rounding_size=1.6",
                                fc=ACC, ec=BOR, lw=1.1, zorder=2))
    ax.add_patch(FancyBboxPatch((2, y - Hh), 2.6, Hh, boxstyle="round,pad=0,rounding_size=1.6",
                                fc=ORG, ec=ORG, lw=0, zorder=3))
    ax.text(7.0, y - 2.4, head, ha="left", va="center", fontsize=13.5, color=NAVY, fontweight="bold", zorder=4)
    ax.text(7.0, y - 4.9, body, ha="left", va="center", fontsize=11.2, color="#243447", zorder=4)
    if i < len(stages) - 1:
        arrow(50, y - Hh - 0.3, y - Hh - 2.3, lw=1.9)
    y -= Hh + 2.7

arrow(50, y - 0.3, y - 2.6, lw=1.9)
y -= 3.2
box(2, y - 7.4, 46.5, 7.4, "OUTPUTS\nHTML · JSON · JUnit · GitHub status", "#2E5C8A", "#2E5C8A", fs=11.6, weight="normal")
box(51.5, y - 7.4, 46.5, 7.4, "STORE\nSQLite or PostgreSQL", "#2E5C8A", "#2E5C8A", fs=11.6, weight="normal")

plt.subplots_adjust(0, 0, 1, 1)
fig.savefig(f"{OUT}/architecture.png", dpi=200, facecolor="white")
plt.close(fig)
print("architecture ok")

# ------------------------------------------------------------------- charts
bm = json.load(open(os.path.join(ROOT, "reports", "benchmark-summary.json"), encoding="utf-8"))
# The strict summary, not live-eval-summary-taxonomy.json. ADR 0006 decides the
# headline figure is the strict 94.20%, with the tolerant grouping published
# beside it rather than in its place — a poster chart titled with the tolerant
# number is exactly the substitution that ADR rules out.
ev = json.load(open(os.path.join(ROOT, "reports", "live-eval-summary.json"), encoding="utf-8"))

fig, a2 = plt.subplots(1, 1, figsize=(6.6, 3.15), dpi=200)

seeds = [p["accuracy"] * 100 for p in ev["per_seed"]]
xs = list(range(1, len(seeds) + 1))
lo, hi, mean = ev["ci95_low"] * 100, ev["ci95_high"] * 100, ev["pooled_accuracy"] * 100
a2.axhspan(lo, hi, color="#FD6925", alpha=0.16, zorder=1,
           label="95% CI  {:.2f}–{:.2f}%".format(lo, hi))
a2.axhline(mean, color="#FD6925", lw=2.0, zorder=3,
           label="pooled  {:.2f}%  (n=500)".format(mean))
a2.plot(xs, seeds, "o-", color="#2E5C8A", lw=2.0, ms=7, zorder=4, label="per-seed accuracy (50 trials each)")
a2.set_xticks(xs); a2.set_xlabel("random seed", fontsize=12, color="#243447")
a2.set_ylabel("accuracy (%)", fontsize=12, color="#243447")
a2.set_ylim(88, 100.5)
a2.set_title("Change classification — {:.2f}%, across-seed σ {:.2f}%".format(mean, ev["across_seed_stdev"] * 100),
             fontsize=14, color=NAVY, fontweight="bold", pad=10)
a2.legend(fontsize=11, loc="lower left", framealpha=0.95, ncol=1)
for s in ("top", "right"): a2.spines[s].set_visible(False)
a2.spines["left"].set_color(BOR); a2.spines["bottom"].set_color(BOR)
a2.tick_params(labelsize=11.5, colors="#243447")
a2.grid(axis="y", color="#E3E8EF", lw=0.8, zorder=0)

fig.savefig(f"{OUT}/charts.png", dpi=200, facecolor="white", bbox_inches="tight")
plt.close(fig)
print("charts ok")

# --------------------------------------------------------------- triptych
RUN = os.path.join(ROOT, ".visual-regression", "runs",
                   "20260727-173710-512531_demo-home-en_chromium_desktop_default")
crop = (0, 0, 1440, 560)
b = Image.open(f"{RUN}/baseline.webp").convert("RGB").crop(crop)
c = Image.open(f"{RUN}/current.webp").convert("RGB").crop(crop)
dv = Image.open(f"{RUN}/diff_overlay.webp").convert("RGB").crop(crop)

W = 1320; PAD = 14; LAB = 40
half = (W - 3 * PAD) // 2
hh = int(half * crop[3] / crop[2])
full = W - 2 * PAD
fh = int(full * crop[3] / crop[2])
H = LAB + hh + PAD + LAB + fh + PAD
canvas = Image.new("RGB", (W, H), "white")
dr = ImageDraw.Draw(canvas)
fl = ImageFont.truetype(DJV_B, 24)

def place(img, x, y, w, h, label, color):
    dr.text((x, y + 8), label, font=fl, fill=color)
    im = img.resize((w, h), Image.LANCZOS)
    canvas.paste(im, (x, y + LAB))
    dr.rectangle([x, y + LAB, x + w - 1, y + LAB + h - 1], outline="#C7D0DC", width=2)

place(b, PAD, 0, half, hh, "BASELINE (approved reference)", "#10294A")
place(c, PAD * 2 + half, 0, half, hh, "CURRENT (after code change)", "#10294A")
place(dv, PAD, LAB + hh + PAD, full, fh, "DIFF OVERLAY  →  FAIL", "#D6006E")
canvas.save(f"{OUT}/triptych.png")
print("triptych ok", canvas.size)
