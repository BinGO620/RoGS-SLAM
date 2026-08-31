#!/usr/bin/env python3
"""Convert the manuscript markdown body to LNCS LaTeX, so the page budget can be
measured against a real compile instead of a words-per-page estimate.

Why this exists: the whole page account in WRITING_ROADMAP.md §四-A rests on an
assumed 520 words/page. That constant was never checked against a build, and a
compression pass sized by a wrong constant is wasted work. This converter makes the
check cheap and repeatable.

Scope: it handles exactly the constructs the manuscript uses -- ATX headings, bold,
italic, inline code, inline and display math, pipe tables, blockquote figure
captions, numbered and bulleted lists, and em/en dashes. It is not a general
markdown implementation and does not try to be; anything it does not recognise it
passes through with LaTeX specials escaped, and it reports what it skipped.

Usage:
    python scripts/md2latex_manuscript.py papers/maskfree_bundle/manuscript.md \
        --out papers/maskfree_bundle/latex/body_v2.tex \
        --figdir papers/maskfree_bundle/figures
"""
from __future__ import annotations

import argparse
import os
import re

# LaTeX specials that must be escaped in text, EXCLUDING those we generate ourselves
# and excluding $ (math is extracted before escaping).
_ESCAPE = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def _protect_math(text):
    """Pull $...$ spans out so escaping cannot touch them. Returns (text, spans)."""
    spans = []

    def _take(m):
        spans.append(m.group(0))
        return f"\x00{len(spans) - 1}\x00"

    # inline math only here; display math is handled at block level
    return re.sub(r"\$[^$\n]+\$", _take, text), spans


def _protect_cite(text, spans):
    r"""Pull raw LaTeX \cite{...} / \ref{...} commands through unescaped.

    The manuscript markdown carries \cite{key} verbatim (the .bib is the source of
    truth for keys); without this the escaping stage turns them into
    \textbackslash{}cite\{key\} and BibTeX sees no citations at all.
    """
    def _take(m):
        spans.append(m.group(0))
        return f"\x00{len(spans) - 1}\x00"

    return re.sub(r"\\(?:cite|ref|label|eqref)\{[^}\n]*\}", _take, text), spans


def _protect_code(text, spans):
    def _take(m):
        inner = m.group(1)
        # \texttt needs its own escaping, and _ is common in our identifiers
        inner = inner.replace("\\", r"\textbackslash{}")
        for ch, rep in (("_", r"\_"), ("&", r"\&"), ("%", r"\%"), ("#", r"\#"),
                        ("{", r"\{"), ("}", r"\}"), ("$", r"\$"),
                        ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}"),
                        ("\u00b7", r"\textperiodcentered{}"),
                        ("\u2212", "-")):
            inner = inner.replace(ch, rep)
        spans.append(r"\texttt{" + inner + "}")
        return f"\x00{len(spans) - 1}\x00"

    return re.sub(r"`([^`]+)`", _take, text), spans


def _escape(text):
    out = []
    for ch in text:
        out.append(_ESCAPE.get(ch, ch))
    return "".join(out)


def _restore(text, spans):
    def _put(m):
        return spans[int(m.group(1))]

    return re.sub(r"\x00(\d+)\x00", _put, text)


def inline(text):
    """Markdown inline -> LaTeX inline, math and code protected from escaping."""
    # "~\cite{key}" is a LaTeX tie (non-breaking space before a citation), not a
    # literal tilde -- without this guard _escape printed "\textasciitilde{}"
    # before every citation in the compiled PDF.
    text = text.replace("~\\cite", "\x00TIE\x00\\cite")
    text, spans = _protect_math(text)
    text, spans = _protect_cite(text, spans)
    text, spans = _protect_code(text, spans)
    text = _escape(text)
    # bold then italic (bold first so **x** is not eaten by the italic rule)
    text = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", text, flags=re.S)
    text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"\\emph{\1}", text)
    # typographic dashes: keep the source's intent
    text = text.replace("—", "---").replace("–", "--")
    text = text.replace("×", r"$\times$").replace("≥", r"$\ge$").replace("≤", r"$\le$")
    text = text.replace("≈", r"$\approx$")
    # NB: _escape() has already run, so the underscore arrives as "\_"
    text = re.sub(r"Δ\\_([A-Za-z])", r"$\\Delta_\1$", text)
    text = text.replace("Δ", r"$\Delta$")
    text = text.replace("τ", r"$\tau$").replace("δ", r"$\delta$")
    text = text.replace("±", r"$\pm$").replace("→", r"$\rightarrow$")
    # A bold best-value cell "**1.5±0.1**" becomes \textbf{1.5$\pm$0.1}, but math
    # mode ignores the surrounding \textbf -- the ±0.1 half printed regular and
    # the "best per column" bolding read as missing. Re-emit such cells as a
    # bold-math group so the whole cell is visibly bold.
    text = re.sub(r"\\textbf\{(\d+\.?\d*)\$\\pm\$(\d+\.?\d*)\}",
                  r"{\\boldmath$\1\\pm\2$}", text)
    # U+2212 MINUS SIGN is absent from the LaTeX text fonts and XeTeX drops it
    # silently -- which once turned a load-bearing "-0.182" into "0.182". Map it to
    # a math minus, and see _unrepresentable() below for the guard that keeps any
    # future such character from passing quietly.
    text = text.replace("\u2212", "$-$")
    text = text.replace("§", r"\S{}").replace("·", r"$\cdot$")
    # U+2020 DAGGER is a standard LaTeX symbol (tables use it for footnote marks)
    text = text.replace("†", r"\dag{}").replace("‡", r"\ddag{}")
    text = text.replace("÷", r"$\div$")
    text = text.replace("⇒", r"$\Rightarrow$").replace("⬜", "").replace("✅", "")
    text = text.replace("⚠", "").replace("★", "").replace("🟡", "")
    text = text.replace("\u201c", "``").replace("\u201d", "''")
    # Straight double quotes: this paper quotes competitors verbatim throughout, and
    # LaTeX renders a bare " as a right-double-quote on BOTH ends. Pair them up.
    text = re.sub(r'"([^"\n]*)"', r"``\1''", text)
    text = text.replace("‘", "`").replace("’", "'")
    return _restore(text, spans).replace("\x00TIE\x00", "~")



# Characters that the LaTeX text fonts do not carry. XeTeX drops these SILENTLY, so a
# converter without this guard can change what the paper says -- U+2212 once turned a
# load-bearing "-0.182" into "0.182" in the factorial table. Anything non-ASCII that
# survives conversion is reported and, unless --allow-unrepresentable is passed, is an
# error: a build that quietly alters a number is worse than no build.
def unrepresentable(tex):
    """Return {char: count} for non-ASCII characters left after conversion."""
    from collections import Counter
    return Counter(ch for ch in tex if ord(ch) > 127)


def convert(md, skip_before=None, stop_at=None, figdir=None):
    lines = md.split("\n")
    out, skipped = [], []
    sbs_pending = False
    _sbs_left = None
    i = 0
    started = skip_before is None

    while i < len(lines):
        ln = lines[i]

        if not started:
            if ln.startswith(skip_before):
                started = True
            else:
                i += 1
                continue
        if stop_at and ln.startswith(stop_at):
            break

        # ---- display math ----
        if ln.strip().startswith("$$"):
            block = [ln]
            if not ln.strip().endswith("$$") or len(ln.strip()) == 2:
                i += 1
                while i < len(lines) and "$$" not in lines[i]:
                    block.append(lines[i])
                    i += 1
                if i < len(lines):
                    block.append(lines[i])
            body = "\n".join(block).replace("$$", "").strip().rstrip(",")
            out.append("\\begin{equation}\n" + body + "\n\\end{equation}\n")
            i += 1
            continue

        # ---- headings ----
        m = re.match(r"^(#{1,4})\s+(.*)$", ln)
        if m:
            depth, title = len(m.group(1)), m.group(2).strip()
            title = re.sub(r"^\d+(\.\d+)*\.?\s*", "", title)  # LaTeX numbers them
            cmd = {1: "section", 2: "subsection", 3: "subsubsection",
                   4: "paragraph"}[depth]
            out.append(f"\\{cmd}{{{inline(title)}}}\n")
            i += 1
            continue

        # ---- `<!--sbs-->` between two table blocks: pop the last emitted
        # table float and pack it with the NEXT table into one float ----
        if re.match(r"^\s*<!--sbs-->\s*$", ln):
            for j in range(len(out) - 1, -1, -1):
                if "\\begin{table}" in out[j]:
                    tab_part = out[j + 1].replace("\\end{table}", "")
                    _sbs_left = (tab_part, "")
                    del out[j:j + 2]
                    sbs_pending = True
                    break
            i += 1
            continue

        # ---- pipe table ----
        if ln.lstrip().startswith("|") and i + 1 < len(lines) and \
                re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(lines[i])
                i += 1
            header = [c.strip() for c in rows[0].strip().strip("|").split("|")]
            align_src = [c.strip() for c in rows[1].strip().strip("|").split("|")]
            base = ["r" if a.endswith(":") and not a.startswith(":")
                    else "c" if a.startswith(":") and a.endswith(":")
                    else "l" for a in align_src]
            # A cell holding a long list (e.g. nine sequence names) cannot be set in an
            # `l` column without running into the margin -- one such cell overflowed by
            # 218pt. Give any column with a long cell a wrapping p{} of the leftover
            # width, estimating ~0.145 cm per character at footnotesize.
            body_rows = [[c.strip() for c in r.strip().strip("|").split("|")]
                         for r in rows[2:]]
            colmax = []
            for ci in range(len(header)):
                widest = len(header[ci]) if ci < len(header) else 0
                for cells in body_rows:
                    if ci < len(cells):
                        widest = max(widest, len(cells[ci]))
                colmax.append(widest)
            CHAR_CM, TEXT_CM = 0.145, 12.2
            wide = [ci for ci, w in enumerate(colmax) if w > 45]
            if wide:
                others = sum(colmax[ci] for ci in range(len(colmax)) if ci not in wide)
                spare = TEXT_CM - CHAR_CM * others - 0.4 * len(colmax)
                per = max(2.5, spare / len(wide))
                for ci in wide:
                    base[ci] = "p{%.2fcm}" % per
            align = "".join(base)
            # Wide tables overflow the LNCS text block at footnotesize -- the
            # 6-column factorial table ran 90pt over. Step the size down and tighten
            # the column padding rather than letting it bleed into the margin.
            size = "\\scriptsize" if len(header) >= 6 else "\\footnotesize"
            pad = "\\setlength{\\tabcolsep}{3.5pt}" if len(header) >= 6 else ""
            # The master table's method-name column holds long labels
            # ("MRCS mask-free (ours)"); a wrapping ragged p{} keeps the table
            # inside the text block where an l-column would push it into the
            # margin. Wide enough that "MRCS combined" fits its line, so the
            # label wraps as "MRCS combined" / "(ours)" instead of hyphenating
            # ("com-bined"); ragged right suppresses justification hyphenation.
            if header and header[0] == "Method":
                align = (">{\\raggedright\\arraybackslash}p{2.12cm}"
                         + align[1:])
                pad = "\\setlength{\\tabcolsep}{2.5pt}"
            tab = ["\\begin{tabular}{" + align + "}\\toprule",
                   " & ".join(inline(c) for c in header) + r" \\ \midrule"]
            first_body = True
            for r in rows[2:]:
                cells = [c.strip() for c in r.strip().strip("|").split("|")]
                cells += [""] * (len(header) - len(cells))
                # A row whose only non-empty cell is _Name_ is a group header
                # (method class in the master table): render it as a spanning
                # italic multicolumn row, separated from the previous group by
                # a rule, instead of an underscored pseudo-row.
                if (cells[0].startswith("_") and cells[0].endswith("_")
                        and len(cells[0]) > 2 and not any(cells[1:])):
                    if not first_body:
                        tab.append("\\midrule")
                    tab.append("\\multicolumn{%d}{l}{\\emph{%s}} \\\\"
                               % (len(header), inline(cells[0][1:-1])))
                    first_body = False
                    continue
                tab.append(" & ".join(inline(c) for c in cells[:len(header)]) + r" \\")
                first_body = False
            tab.append("\\bottomrule\\end{tabular}")
            tab_latex = "\n".join(tab)

            # A caption paragraph is a body paragraph opening with bold
            # "**Table N.**" directly above the table. Absorb it into the float
            # as a real \caption (LaTeX numbers the table itself), so the
            # printed table is self-describing instead of preceded by a fake
            # in-text paragraph. Blank-line entries between the two are skipped.
            cap = None
            j = len(out) - 1
            while j >= 0 and not out[j].strip():
                j -= 1
            if j >= 0 and out[j].lstrip().startswith(r"\textbf{Table"):
                cap = re.sub(r"^\\textbf\{Table\s*\d+\.\}\s*", "",
                             out[j].strip())
                del out[j:]

            if sbs_pending:
                # each tabular is wrapped in \resizebox so it cannot overflow its
                # minipage and collide with its neighbour (the 6-col attribution
                # table is wider than 0.492\textwidth at scriptsize)
                out.append("\\begin{table}[t]\\centering" + size)
                out.append("\\begin{minipage}[t]{0.492\\textwidth}\\centering"
                           + _sbs_left[1]
                           + "\\resizebox{\\linewidth}{!}{" + _sbs_left[0] + "}"
                           + "\\end{minipage}%")
                out.append("\\hfill")
                out.append("\\begin{minipage}[t]{0.492\\textwidth}\\centering"
                           + "\\resizebox{\\linewidth}{!}{" + tab_latex + "}"
                           + "\\end{minipage}"
                           "\\end{table}")
                sbs_pending = False
                continue
            out.append("\\begin{table}[t]\\centering" + size + pad)
            if cap is not None:
                out.append(tab_latex + "\n\\caption{" + cap + "}\\end{table}")
            else:
                out.append(tab_latex + "\\end{table}")
            continue

        # ---- blockquote (figure caption in our document) ----
        if ln.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i].lstrip(">").strip())
                i += 1
            text = " ".join(x for x in buf if x)
            # A caption names its own asset as `figures/<file>` -- include the real
            # graphic when it exists, so the page budget reflects the actual figure
            # rather than a placeholder of a guessed size.
            m = re.search(r"`(figures/[\w./-]+)`", text)
            asset = m.group(1) if m else None
            # Optional per-figure width, written in the blockquote as
            # `width=0.78` (fraction of \textwidth); default is full width.
            wm = re.search(r"width=(0?\.\d+|1(?:\.0+)?)\.?\s*$", text)
            figwidth = wm.group(1) if wm else None
            if figwidth:
                text = text[:wm.start()].rstrip().rstrip(",").rstrip()
            # The blockquote opens by naming its own asset: `**Figure N**
            # (`figures/x.pdf`).` That tag is source-level addressing, not
            # caption prose -- strip it so the printed caption starts at the
            # italic lede (exp49 removed the filename mark from captions).
            text = re.sub(r"^\*\*Figure\s+\d+\*\*\s*\(`figures/[\w./-]+`\)\.\s*",
                          "", text)
            if asset and figdir and os.path.exists(os.path.join(figdir, os.path.basename(asset))):
                width = (figwidth + r"\textwidth") if figwidth else r"\textwidth"
                graphic = (r"\includegraphics[width=" + width + "]{"
                           + os.path.basename(asset) + "}")
            else:
                if asset:
                    skipped.append(f"figure asset not found, placeholder used: {asset}")
                graphic = r"\rule{0.6\textwidth}{3.2cm}"
            out.append("\\begin{figure}[t]\\centering\n" + graphic + "\n"
                       f"\\caption{{{inline(text)}}}\\end{{figure}}\n")
            continue

        # ---- lists ----
        if re.match(r"^\s*\d+\.\s", ln) or re.match(r"^\s*[-*]\s", ln):
            ordered = bool(re.match(r"^\s*\d+\.\s", ln))
            env = "enumerate" if ordered else "itemize"
            items = []
            while i < len(lines) and (re.match(r"^\s*\d+\.\s", lines[i])
                                      or re.match(r"^\s*[-*]\s", lines[i])
                                      or (lines[i].startswith("   ") and lines[i].strip())):
                if re.match(r"^\s*\d+\.\s", lines[i]) or re.match(r"^\s*[-*]\s", lines[i]):
                    items.append(re.sub(r"^\s*(?:\d+\.|[-*])\s+", "", lines[i]))
                else:
                    items[-1] += " " + lines[i].strip()
                i += 1
            out.append(f"\\begin{{{env}}}")
            for it in items:
                out.append(r"\item " + inline(it))
            out.append(f"\\end{{{env}}}\n")
            continue

        # ---- horizontal rule / blank ----
        if ln.strip() in ("---", "***", ""):
            out.append("")
            i += 1
            continue

        # ---- paragraph ----
        para = [ln]
        i += 1
        while i < len(lines) and lines[i].strip() and \
                not lines[i].startswith(("#", ">", "|", "---")) and \
                not lines[i].strip().startswith("$$") and \
                not re.match(r"^\s*(?:\d+\.|[-*])\s", lines[i]):
            para.append(lines[i])
            i += 1
        out.append(inline(" ".join(x.strip() for x in para)) + "\n")

    tex = "\n".join(out)
    # Consecutive list items separated by a blank line become separate environments,
    # which both restarts the numbering and adds spurious vertical space (and so
    # inflates the very page count this script exists to measure). Re-join them.
    for env in ("enumerate", "itemize"):
        tex = re.sub(r"\\end\{" + env + r"\}\s*\n\s*\n\s*\\begin\{" + env + r"\}",
                     "", tex)
    return tex, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("md")
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", default="# 1. Introduction",
                    help="first line of body content (front-matter is dropped)")
    ap.add_argument("--stop", default="# Evidence appendix",
                    help="stop before this line (appendix is not part of the paper)")
    ap.add_argument("--allow-unrepresentable", action="store_true",
                    help="downgrade the non-ASCII guard from an error to a warning")
    ap.add_argument("--figdir", default=None,
                    help="directory holding the figure assets named in captions")
    a = ap.parse_args()

    md = open(a.md, encoding="utf-8").read()
    tex, skipped = convert(md, skip_before=a.start, stop_at=a.stop, figdir=a.figdir)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("% GENERATED by scripts/md2latex_manuscript.py -- do not edit by hand.\n")
        fh.write(f"% source: {a.md}\n\n")
        fh.write(tex)

    words = len(re.sub(r"\s+", " ", tex).split())
    print(f"wrote {a.out}  ({words} tokens of LaTeX)")
    if skipped:
        print("SKIPPED constructs:", skipped)

    bad = unrepresentable(tex)
    if bad:
        detail = ", ".join(f"U+{ord(c):04X} {c!r} x{n}" for c, n in bad.most_common())
        msg = ("non-ASCII characters survived conversion; XeTeX may DROP these "
               "silently and change what the paper says: " + detail)
        if a.allow_unrepresentable:
            print("WARNING:", msg)
        else:
            raise SystemExit("ERROR: " + msg +
                             "\n  add a mapping in inline(), or pass "
                             "--allow-unrepresentable if they are genuinely safe.")
    print("character check: all output is ASCII")


if __name__ == "__main__":
    main()
