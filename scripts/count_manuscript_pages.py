"""Word/page accounting for the manuscript, excluding non-paper material.

CALIBRATED AGAINST A REAL COMPILE (2026-08-25, exp46). The rate used to be an
assumed 520 words/page that had never been checked. A four-length tectonic build of
the v1 body under llncs.cls measured 452 visible-LaTeX-words/page and 1.48 pages of
fixed front-matter overhead, which in this script's markdown-word unit is
~477 words/page -- the old constant was 9% optimistic, and the old front-matter
allowance (0.50 page) was ~1.0 page too small. Evidence, including the residuals of
the linear fit and what the calibration build was missing:
results/evidence/latex_page_rate_calibration.md

Figure captions are charged to the float budget, not the text budget, so they are
counted separately -- otherwise adding a caption looks like text bloat.

Read the output as +/- 1 page: page-break quantisation gives the measured rate about
8% spread, so this is a planning instrument, not a half-page-accurate one.
"""
import re

# markdown words per page, measured (was an assumed 520; see module docstring)
RATE = 477.0
# pages consumed by title block + abstract + keywords, measured as the intercept of
# the four-point fit (was assumed 0.50)
FRONT_MATTER = 1.48
# Area of the graphics themselves (captions are counted separately from their words).
# Measured from the assets at \textwidth = 12.2 cm against a 19.3 cm text height:
#   Fig1 12.2x5.9 = 0.30 | Fig2 12.2x4.28 = 0.22 | Fig3 12.2x5.9 = 0.30
# UPDATE THIS if the float set changes -- it is not derived from the markdown.
FIGURE_AREA = 0.82
path = "papers/maskfree_bundle/manuscript.md"
txt = open(path, encoding="utf-8").read()

# drop the evidence appendix: explicitly not part of the submitted paper
txt = txt.split("# Evidence appendix")[0]

# blockquote runs that are figure captions are float budget, not text budget
caption_words = 0
def _strip_captions(s):
    global caption_words
    out, buf = [], []
    for line in s.split("\n"):
        if line.startswith("> "):
            buf.append(line)
            continue
        if buf:
            blk = "\n".join(buf)
            if "**Figure" in blk:
                caption_words += len(blk.split())
            else:
                out.extend(buf)
            buf = []
        out.append(line)
    if buf:
        blk = "\n".join(buf)
        if "**Figure" in blk:
            caption_words += len(blk.split())
        else:
            out.extend(buf)
    return "\n".join(out)

txt = _strip_captions(txt)

# the file's own front-matter (discipline notes, status table) is not paper text: drop
# everything before the FIRST numbered section, whichever it is
m = re.search(r"\n# \d\. ", txt)
if m:
    txt = txt[m.start() + 1:]

secs = re.split(r"\n# (?=\d\. )", txt)
total = 0
written = set()
print(f"{'section':30s} {'words':>7s} {'pages':>7s}  {'budget':>7s}  {'delta':>7s}")
print("-" * 64)
BUDGET = {"1": 1.5, "2": 1.5, "3": 2.2, "4": 0.8, "5": 2.5, "6": 0.7, "7": 0.3}
for s in secs:
    head = s.split("\n", 1)[0].strip().lstrip("# ")
    if not head or not head[0].isdigit():
        continue
    n = len(s.split())
    total += n
    num = head[0]
    written.add(num)
    b = BUDGET.get(num)
    d = f"{n / RATE - b:+.2f}" if b else "  —"
    bs = f"{b:.2f}" if b else "  —"
    print(f"{head[:30]:30s} {n:7d} {n / RATE:7.2f}  {bs:>7s}  {d:>7s}")
print("-" * 64)
print(f"{'TEXT TOTAL (drafted)':30s} {total:7d} {total / RATE:7.2f}")
print(f"{'figure captions (float)':30s} {caption_words:7d} {caption_words / RATE:7.2f}")

unwritten = {k: v for k, v in BUDGET.items() if k not in written}
un_total = sum(unwritten.values())
print()
print("BUDGET: 12.0 pages of LNCS body (references are outside it, per the call).")
if unwritten:
    print("  not yet drafted (charged at budget): "
          + " · ".join(f"§{k} {v:.1f}" for k, v in sorted(unwritten.items()))
          + f" = {un_total:.2f}")
prose = total / RATE
caps = caption_words / RATE
proj = prose + caps + un_total + FRONT_MATTER + FIGURE_AREA
print(f"  prose {prose:.2f} + captions {caps:.2f} + front matter {FRONT_MATTER:.2f}"
      f" + figure area {FIGURE_AREA:.2f}"
      + (f" + unwritten {un_total:.2f}" if un_total else "")
      + f" = {proj:.2f} pages (+/- 1)")
print(f"  vs 12.0 allowed  =>  must cut {max(0.0, proj - 12.0):.2f} pages")
print()
print("  last real compile: 18 pages, v1 body with ALL THREE figures, no bibliography")
print("  (results/evidence/latex_page_rate_calibration.md). Re-measure after any")
print("  change to the float set or the abstract length.")
