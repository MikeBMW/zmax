---
name: powerpoint
description: Create, read, edit .pptx decks with python-pptx.
version: 1.1.0
author: Nous Research
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [pptx, powerpoint, presentations, slides, office, python-pptx]
    category: productivity
    related_skills: [docx, xlsx, pdf]
---

# Powerpoint Skill

Create, inspect, and edit PowerPoint (.pptx) presentations using the
python-pptx library. Five helper scripts cover deck creation from a JSON
spec, structured read-back, in-place edits, template-driven brand decks,
and slide rendering — all offline, no PowerPoint installation required.

## When to Use

- The user asks to build a slide deck, report presentation, or pitch deck.
- You need to extract text, notes, tables, chart data, or images from a
  .pptx someone shared.
- You need to update an existing deck: replace text, refresh or patch
  chart data, swap a logo, duplicate/remove/reorder slides, set
  backgrounds, footers, hyperlinks, or speaker notes.
- You must produce an on-brand deck from a company .pptx template.
- Do NOT use this for .ppt (legacy binary) files — convert them first with
  `soffice --convert-to pptx old.ppt` if LibreOffice is available.

## Prerequisites

- Python 3.10+ with `python-pptx` installed
  (`pip install python-pptx`).
- Optional: LibreOffice (`soffice`) plus poppler (`pdftoppm` or
  `pdftocairo`) for rendering slides to PNGs and for PDF export.
  `pptx_render.py` detects both with `shutil.which` and degrades
  gracefully (reports `{"rendered": false, "missing": [...]}`, exit 0)
  when absent — all create/read/edit operations work without them.
- Check availability via `terminal`:
  `python -c "import pptx; print(pptx.__version__)"` and `which soffice pdftoppm`.

## How to Run

All scripts live in `scripts/`, take `--help`, print JSON to stdout, and
exit non-zero on failure. Run them with `terminal`:

```bash
python scripts/pptx_create.py deck.json out.pptx
python scripts/pptx_read.py deck.pptx --outline      # full JSON outline
python scripts/pptx_read.py deck.pptx --notes        # speaker notes
python scripts/pptx_read.py deck.pptx --images ./img # export pictures
python scripts/pptx_edit.py deck.pptx --replace-text "Old Corp" "New Corp"
python scripts/pptx_edit.py deck.pptx --chart-data update.json
python scripts/pptx_edit.py deck.pptx --duplicate-slide 2
python scripts/pptx_edit.py deck.pptx --remove-slide 3 --move-slide 2 0
python scripts/pptx_from_template.py brand.pptx out.pptx --values vals.json
python scripts/pptx_render.py deck.pptx --outdir ./render  # slide PNGs
```

Author JSON specs with `write_file`; inspect script output and generated
JSON with `read_file`.

## Quick Reference

| Task | Command |
|---|---|
| New deck from spec | `pptx_create.py spec.json out.pptx` |
| 16:9 vs 4:3 | `"slide_size": "16:9"` or `"4:3"` in the spec |
| Outline as JSON | `pptx_read.py deck.pptx --outline` |
| Export images | `pptx_read.py deck.pptx --images DIR` |
| Replace text | `pptx_edit.py deck.pptx --replace-text OLD NEW` |
| Replace chart data | `pptx_edit.py deck.pptx --chart-data spec.json` |
| Patch one series | same flag, spec with `"ops"` (see below) |
| Swap picture | `pptx_edit.py deck.pptx --swap-image N NAME new.png` |
| Duplicate slide | `pptx_edit.py deck.pptx --duplicate-slide N` |
| Remove slide | `pptx_edit.py deck.pptx --remove-slide N` |
| Reorder slide | `pptx_edit.py deck.pptx --move-slide FROM TO` |
| Slide background | `pptx_edit.py deck.pptx --set-background N RRGGBB` |
| Hyperlink runs | `pptx_edit.py deck.pptx --hyperlink N TEXT URL` |
| Slide number on | `pptx_edit.py deck.pptx --enable-slide-number N` |
| Footer text | `pptx_edit.py deck.pptx --set-footer N TEXT` |
| Set notes | `pptx_edit.py deck.pptx --set-notes N TEXT` |
| Append notes | `pptx_edit.py deck.pptx --append-notes N TEXT` |
| Fill template | `pptx_from_template.py tpl.pptx out.pptx --values v.json` |
| Render slide PNGs | `pptx_render.py deck.pptx --outdir DIR` |

## Procedure

### 1. Create a deck

Write a JSON spec (see `pptx_create.py --help` for the full format), then
run `pptx_create.py`. Per slide you can set: `layout` (title,
title_content, section, two_content, title_only, blank), `title`,
`subtitle`, `bullets` (strings, or dicts with `level` 0-4, `size` pt,
`bold`, `italic`, `font`, `color` hex, `link` URL for a hyperlink),
`background` (solid hex), `footer` (text; enables the layout's footer
placeholder), `slide_number` (true; enables the layout's slide-number
placeholder), `images` (path + left/top/width/height in inches), `tables`
(`rows` as list-of-lists), `shapes` (rectangle, rounded_rectangle, oval,
diamond, right_arrow, chevron, with `fill` hex + optional `text`),
`charts` (bar, bar_h, line, pie with `categories` + `series`), and
`notes` (speaker notes).

### 2. Read a deck

`pptx_read.py deck.pptx --outline` returns slide size, layout inventory,
and per slide: layout name, all shape texts, table cells, image inventory
(filename/ext/bytes), chart categories/series/values, and speaker notes.
Use `--images DIR` to dump embedded pictures to files, then
`vision_analyze` on any exported image if you need to see its content.

### 3. Edit a deck

`pptx_edit.py` combines operations in one pass; use `--output` to keep the
original. Text replacement scans slide shapes, table cells, and notes.
Image swap retargets the picture's relationship id so position and size
are preserved. Slide removal drops the relationship and the `<p:sldId>`
entry; reorder moves the `<p:sldId>` element within `<p:sldIdLst>`
(python-pptx has no public API for either — the script does the XML-level
work). `--duplicate-slide N` appends an independent deep copy of slide N:
shape XML plus image/media/hyperlink relationships are cloned and rIds
remapped, so editing the copy never touches the original. Chart slides
are refused (see Pitfalls). `--set-notes`/`--append-notes` edit speaker
notes; `--set-background`, `--hyperlink`, `--enable-slide-number`, and
`--set-footer` handle deck polish.

Chart updates take a JSON spec via `--chart-data`. Full replace:
`{"slide": 0, "chart": 0, "categories": [...], "series": {...}}`. For
surgical edits, pass `"ops"` instead — a list of
`{"op": "update_series", "name": ..., "values": [...]}`,
`add_series`, `remove_series`, `rename_category` (`from`/`to` or
`index`), and `set_title`. python-pptx can only swap a chart's entire
dataset (`replace_data`), so ops are implemented as read-existing →
modify → replace; the per-part UX is a wrapper, and any chart data not
expressible as categories + numeric series will be normalized by the
round-trip.

### 4. Build from a template

`pptx_from_template.py` opens a brand .pptx, replaces every
`{{token}}` from a values JSON across slides/tables/notes, and can append
new slides that use the template's own layouts (by layout name or index)
so they inherit the master's fonts and colors. Tip: to start from a
template with zero slides, delete existing ones afterward with
`pptx_edit.py --remove-slide`.

### 5. Visual verification

`pptx_render.py deck.pptx --outdir ./render` converts the deck to PDF
with `soffice --headless` and splits it into one PNG per slide with
`pdftoppm` (or `pdftocairo`). Output JSON lists the PNG paths — review
each with `vision_analyze`. When either tool is missing the script exits
0 with `{"rendered": false, "missing": [...]}` and guidance; fall back to
the JSON outline from `pptx_read.py`, which verifies content and
structure, just not visuals.

## Converting to PDF

If LibreOffice is installed, export the finished deck to PDF directly:

```bash
soffice --headless --convert-to pdf --outdir ./out deck.pptx
```

The output lands at `./out/deck.pdf`. Fonts not installed on the host are
substituted, so render-verify (Procedure step 5) before shipping the PDF.
There is no offline pure-Python .pptx→PDF path; if `soffice` is absent,
say so rather than approximating.

## Pitfalls

- **Run splitting**: PowerPoint fragments paragraph text into runs at
  spell-check and edit boundaries. `--replace-text` first merges adjacent
  runs whose formatting is identical, so matches split across such runs
  are replaced with formatting fully preserved. Only when a match spans
  *genuinely differently-formatted* runs is the paragraph rewritten with
  the first run's formatting — verify those slides after replacement.
- **Chart slides cannot be duplicated**: each chart relationship embeds a
  separate XLSX workbook part; cloning that graph reliably is not
  supported, so `--duplicate-slide` refuses chart slides cleanly instead
  of corrupting the deck. Rebuild the chart on a new slide instead.
  External-hyperlink and image/media rels are carried over; layout and
  notes rels are recreated fresh.
- **Chart ops are a wrapper**: python-pptx replaces the whole dataset;
  `"ops"` round-trips existing plot data through `replace_data`, and
  changing chart *type* is not possible.
- **Reordering is XML-level**: python-pptx has no supported reorder API.
  `--move-slide` manipulates `<p:sldIdLst>` directly; safe for ordinary
  decks but re-read the deck afterward to confirm.
- **Copying slides between decks is unsupported** — duplication works
  only within one deck, where layouts and masters are shared.
- Footer/slide-number enablement copies the placeholder from the slide's
  layout; on layouts without those placeholders, `--set-footer` fails
  with a clear message (add a textbox instead).
- Hyperlinks apply to whole runs; `--hyperlink` links every run
  containing the given text on that slide.
- The default python-pptx template is 4:3; the create script sets 16:9
  unless the spec says otherwise. Custom templates keep their own size.
- Layout indexes vary by template. For brand templates, list layout names
  first: `pptx_read.py template.pptx --outline` (`layouts_available`).
- `slide.shapes.title` is None on blank layouts — the create script
  handles this, but remember it when writing ad-hoc python-pptx code.
- Always pass `encoding="utf-8"` when writing spec files; tokens like
  `{{city}}` may be filled with non-ASCII values.
- **`✗` (U+2717) / `✘` / `✔` have no glyph in Noto Sans CJK — they render as `.notdef` 豆腐块** (`✓` U+2713 and `◐` U+25D0 do exist). Use `✓` + `×` (U+00D7) for pass/fail marks. Font fallback fails silently, so this is only visible after rendering.
- **图内注释**用 `fig.text(...)` 落在画布外 + `subplots_adjust(bottom=…)` 留边距；写在 `transform=ax.transAxes` 的 0.01–0.05 处必然压最短的那根条或曲线，改完还要重新量图底与页面结论条的距离。
- **2×2 矩阵图的四格标题**放在「离数据点最远的那半格」：点全在顶部就写底部，全在底部就写顶部；硬编码在某个角必然被压。
- **卡片/表格/结论条三者要按页面坐标算一遍**：`卡 y + n×步进` vs `结论 y` vs `页脚 7.02`。这类碰撞最常见，且肉眼看小图看不出来。

- **CJK runs need the East Asian typeface set separately**: `run.font.name
  = "微软雅黑"` only writes `a:latin` — Chinese glyphs fall back to the
  theme font and render wrong. Also append `<a:ea typeface="微软雅黑"/>`
  to the run's `rPr` (helper in `references/cjk-editable-deck.md`).
- **Never derive picture height from width alone.** A tall figure
  (aspect < 0.8) computes `y + h > slide_height` and gets silently
  cropped at the page edge. Contain-fit into the available box
  `min(slide_w - x - margin, footer_y - y)` and scale by the smaller
  factor; passing both `w` and `h` to `add_picture` stretches, it does
  not preserve aspect ratio.
- **Verify overflow by reading the deck back, not by eyeballing.**
  Assert `left>=0, top>=0, left+width<=W, top+height<=H` on every shape;
  full-bleed decoration bars legitimately touch the edge, so whitelist
  them by name rather than loosening the threshold.
- **Slide-preview caches must key on (filename, mtime, size).** Keying on
  name alone serves stale PNGs after every regeneration — the deck looks
  unchanged when it is not.
- **Editability is a spec, not an aspiration.** Native textboxes, real
  tables (`add_table`), and speaker notes with the numbers behind each
  figure; never burn labels into a PNG. Put the source data in a
  side-car JSON next to a generator script so the deck is regenerable.
- **Keep the generator and the shipped deck in ONE directory.** Copying a
  scratch copy of the script over the deliverable-directory copy silently
  reverts every layout fix applied since that copy was made: the pptx is
  right, the script is stale, and the next regenerate undoes the work.
  After any bulk `cp`, gate with a signature diff — for every slide, every
  shape's (name, left, top, width, height, text, table column widths) must
  match between a fresh `python make_deck.py` output and the shipped file
  (see `references/cjk-editable-deck.md` §6). Zero diff is the only
  acceptable result before you trust the script.
- **Sentinel: a table cell that wraps one character onto a second line
  means the column is ~0.15 in too narrow.** Fix by widening the column
  *and* shortening the phrase to a semantic break point (「+」→「·」,
  drop a clause); widening alone just moves the orphan.
- **Do not hand-tune scatter-label offsets.** Moving one label to clear a
  neighbour shoves it onto the next point (four rounds of whack-a-mole in
  practice). Lock `xlim/ylim` first, then loop candidate `xytext` offsets
  scoring each against BOTH collisions — label-label overlap *and*
  label-marker intrusion (point-to-rect distance < marker radius) — and
  take the first zero. Text-vs-text checks alone miss labels crushed by
  markers.
- **A figure's aspect ratio is a deck-layout input.** `bbox_inches="tight"`
  plus an annotation placed far outside the axes turns a wide bar chart
  into a portrait PNG (ar 0.86 instead of 4.7); contain-fit then shrinks
  it to half the intended width and the table below covers it. Pin
  `set_ylim` and skip tight-bbox for figures that must fill a known box.

## Verification

1. After any create/edit, run `pptx_read.py OUT.pptx --outline` and check
   slide count, texts, tables, notes, and chart values match intent.
2. `--images DIR` then file-size check confirms pictures embedded.
3. Render every slide with `pptx_render.py deck.pptx --outdir ./render`
   and review each PNG with `vision_analyze` — this catches overlapping
   shapes, truncated text, and color problems the outline cannot. If the
   render tools are missing, the script says so; rely on the outline.
4. The bundled test suite is the full contract:
   `python -m pytest tests/ -q` (requires python-pptx + pytest).
