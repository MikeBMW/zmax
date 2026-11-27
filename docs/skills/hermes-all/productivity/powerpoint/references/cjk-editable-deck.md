# Editable Chinese-language decks (python-pptx)

Rules that only show up when the deck is authored by script, read by a
CJK audience in PowerPoint/WPS, and shipped as a *editable* deliverable.

## 1. Set both Latin and East Asian typefaces

`run.font.name` writes only `a:latin`. Chinese glyphs then fall back to
the theme font (often a serif or a missing-face box).

```python
from pptx.oxml.ns import qn
from pptx.util import Pt

def set_font(run, size=14, bold=False, color=None, ea="微软雅黑", latin="Arial"):
    f = run.font
    f.size = Pt(size)
    f.bold = bold
    f.name = latin                      # a:latin
    if color is not None:
        f.color.rgb = color
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):        # a:ea = East Asian, a:cs = complex script
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.append(el)
        el.set("typeface", ea)
```

Prefer a face that exists on both reviewer machines and CI render hosts:
`微软雅黑` (Windows), `PingFang SC` (macOS), `Noto Sans CJK SC` (Linux).
LibreOffice substitutes automatically, so a missing face shows up as a
*metric* difference in the PNG preview — check it, do not assume.

## 2. Contain-fit every picture, then clamp to the page

Passing both `w` and `h` to `add_picture` stretches. Deriving `h` from
`w` alone overflows whenever the figure is tall (aspect < 0.8): the
picture's bottom lands below the last usable inch and PowerPoint crops
it — the source PNG is fine, the deck is not.

```python
PAGE_W, PAGE_H, FOOTER_Y = 13.333, 7.5, 6.88   # 16:9 in inches

def pic(slide, path, x, y, w=None, h=None, margin=0.35):
    iw, ih = Image.open(path).size
    ar = iw / ih
    if w and h:                       # given a box -> contain, never stretch
        h = min(h, w / ar)
        w = h * ar
    elif w:
        h = w / ar
    else:
        w = h * ar
    k = min(1.0, (PAGE_W - x - margin) / w, (FOOTER_Y - y) / h)
    w, h = w * k, h * k
    slide.shapes.add_picture(path, Inches(x), Inches(y), Inches(w), Inches(h))
```

## 3. Prove there is no overflow — read the deck back

Cheaper and more reliable than staring at 13 rendered PNGs:

```python
W, H = prs.slide_width / 914400, prs.slide_height / 914400
for i, s in enumerate(prs.slides, 1):
    for sh in s.shapes:
        if None in (sh.left, sh.top, sh.width, sh.height):
            continue
        r = (sh.left + sh.width) / 914400
        b = (sh.top + sh.height) / 914400
        if r > W - 0.1 or b > H - 0.05:
            print("OUT", i, sh.name, round(r, 2), round(b, 2))
```

Full-bleed decoration bars (`0,0,13.333,0.06`) and a cover background
legitimately report as touching the edge — whitelist by shape name
(`if sh.name.startswith(("Rectangle 1", "BG")): continue`) instead of
loosening the threshold until real overflow slips through.

## 4. Two-layer verification before shipping

1. **Structure** — read back: slide count, `has_table` row×col per page,
   picture count, every string, `notes_slide` text. Confirms content and
   that objects really are native (editable).
2. **Pixels** — `soffice --headless --convert-to pdf` then
   `pdftoppm -r 90 -png`; inspect pages for overlap, truncation, font
   substitution. Only the pixels catch a text box that is one line short.

## 5. Serving a deck for preview (web console)

When the deck must be viewable inside a GUI/web console and still
editable by the owner:

- Convert pptx → PDF → per-slide PNG **server-side**, in a child process
  with a timeout; never parse pptx in the UI process.
- Cache under a key of `(filename, mtime, size)`, plus one `meta.json`
  listing page PNGs. mtime changes ⇒ re-convert automatically.
- Serve read-only slide PNGs for the gallery and the **original pptx** as
  an attachment (`application/vnd.openxmlformats-officedocument.presentationml.presentation`)
  so "download / open locally" always yields an editable file.
- Never modify the source pptx; reject path traversal by matching a
  strict basename whitelist (`^[^/\\][^/\\]*\.pptx?$`) and looking the
  name up in a freshly scanned directory listing rather than joining
  user input onto a path.
- Missing `soffice`/`pdftoppm` is a **reported error**, not an empty
  gallery: surface the reason to the page.

## 6. Generator/artifact consistency gate

A deck that is *generated* must be provably regenerable. The failure mode
is quiet: a stale copy of the generator (from `scratch/`, a backup, or a
`cp` in the wrong direction) overwrites the working script; the shipped
.pptx is correct, the script is not, and the next run reverts every
layout fix. Detect it by comparing shape signatures:

```python
def sig(path):
    prs = Presentation(path)
    pages = []
    for s in prs.slides:
        items = []
        for sh in s.shapes:
            txt = sh.text_frame.text if sh.has_text_frame else ""
            if getattr(sh, "has_table", False) and sh.has_table:
                txt = "|".join(c.text for r in sh.table.rows for c in r.cells)
                txt += "|w:" + ",".join("%.2f" % (c.width / 914400) for c in sh.table.columns)
            items.append((sh.name, round((sh.left or 0)/914400, 2),
                          round((sh.top or 0)/914400, 2), round((sh.width or 0)/914400, 2),
                          round((sh.height or 0)/914400, 2), txt))
        pages.append(items)
    return pages
```

Regenerate into a temp path, diff both signatures page by page; require
**0 differences** before declaring the script authoritative. Keep one
canonical copy of the generator inside the deliverable directory and
never `cp` over it from anywhere else.

Also check the sign of the fix itself: a single CJK character wrapping to
its own line means the column is roughly 0.15 in too narrow. Widen the
column *and* move the phrase break to a semantic boundary (`+` → `·`,
drop a clause) — widening alone merely relocates the orphan.

## 7. Inline `**bold**` in textboxes (and the overlap self-check it hides)

A `text()` helper that does `p.add_run(); r.text = line` prints `**`
literally — every emphasis marker in the deck becomes visible garbage.
Parse inline bold once, in the helper, so no page can leak asterisks:

```python
for seg in re.split(r"(\*\*[^*]+\*\*)", line):
    if not seg:
        continue
    r = p.add_run()
    if seg.startswith("**") and seg.endswith("**") and len(seg) > 4:
        r.text, bold_ = seg[2:-2], True
    else:
        r.text, bold_ = seg, bold
    set_font(r, size, bold_, color)
```

Then assert it at build time: `0` shapes whose text still contains `**`,
and a plausible count of bold runs (>0). Cheaper than finding it in a
review screenshot.

**Self-check blind spot:** collecting overlap boxes only from `ax.texts`
misses *label-over-marker* collisions — the labels never overlap each
other, but one sits on a scatter dot and reads as a smudge. Add every
marker to the box set (`ax.transData.transform` + a radius):

```python
for nm, px, py in POINTS:
    cx, cy = ax.transData.transform((px, py)); r = 7.5
    boxes.append(("dot:" + nm,
                  Bbox.from_bounds(cx - r, cy - r, 2 * r, 2 * r)))
```

Two markers 0.5 data-units apart also merge into a figure-eight at normal
marker sizes; either spread the data or shrink the marker.
