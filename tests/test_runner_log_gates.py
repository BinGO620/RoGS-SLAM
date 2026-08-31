"""The console-log gate idiom must FAIL LOUDLY on a malformed count, not silently pass.

exp37 found that every runner in this family wrote

    hits=$(grep -c "pat" "$log" 2>/dev/null || echo 0)

which is broken: ``grep -c`` prints ``0`` AND exits 1 when there are NO matches, so the
``|| echo 0`` fires too and ``hits`` becomes ``"0\\n0"`` and the integer test errors instead
of comparing.

The scope of the damage was measured, not assumed, and it is narrower than first written down:
``grep -c`` exits 1 ONLY on a zero count, so a real (non-zero) count reaches the comparison
clean and IS flagged. Consequently

  * ``if [ "$hits" -gt 0 ]; then bad; else ok; fi``  (exp36 trackside, exp37 hard runner)
    falls to ``else`` on the corrupted zero -- and the true count there really was zero, so it
    was ACCIDENTALLY RIGHT. It was never silently passing violations.
  * ``[ "$hits" -eq 0 ] && ok || bad``  (exp37 paired runner) turns that same corrupted zero
    into a FALSE ALARM -- which is what produced ``violations=6`` on clean data.

No reading changed: exp36's 6 trackside runs really were 0 and the control arms really were 67,
both verified directly on the logs. What changed is that a gate must now reject a malformed
operand instead of taking some branch. These tests pin that, and they exercise the gate against
a KNOWN-BAD input, not only a known-good one.
"""

import os
import re
import subprocess

RUNNERS = (
    "scripts/run_trackside_channel_3090.sh",
    "scripts/run_trackside_hard_3090.sh",
    "scripts/run_trackside_paired_repeats_3090.sh",
)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_no_runner_still_uses_the_broken_grep_idiom():
    for rel in RUNNERS:
        src = "\n".join(l for l in open(os.path.join(_ROOT, rel)).read().splitlines()
                        if not l.strip().startswith("#"))
        assert not re.search(r"grep -c[^\n]*\|\| echo 0\)", src), (
            f"{rel} still pipes grep -c through `|| echo 0`, which yields '0\\n0' on a "
            "zero match and stops the gate from comparing anything")


def test_the_broken_idiom_only_corrupts_the_zero_match_case():
    """The exact scope of the defect, measured rather than assumed.

    ``grep -c`` exits 1 ONLY when the count is zero, so ``|| echo 0`` fires only there. A
    real (non-zero) count therefore reaches the comparison clean and IS flagged. That is why
    the ``-gt 0`` if/else runners were accidentally right -- they were not silently passing
    violations -- while the ``-eq 0 && ok || bad`` form raised 6 false alarms on clean data.
    """
    assert _run_case(0, "broken") == "OK", "zero match: corrupted value falls to else"
    assert _run_case(67, "broken") == "VIOLATION", (
        "a non-zero count is NOT corrupted (grep exits 0), so it is correctly flagged")
    assert _run_case(0, "broken_eq") == "VIOLATION", (
        "the -eq form turns the corrupted zero-match value into a FALSE alarm")
    assert _run_case(67, "broken_eq") == "VIOLATION"


def test_every_runner_guards_against_a_non_integer_count():
    for rel in RUNNERS:
        src = open(os.path.join(_ROOT, rel)).read()
        assert re.search(r"\*\[!0-9\]\*", src), (
            f"{rel} has no non-integer guard on the log count: a malformed value would "
            "take some branch silently instead of failing the gate")
        assert "MALFORMED" in src, f"{rel} never reports a malformed count"


def _run_case(count_lines, style):
    """Exercise the fixed shell logic on a synthetic log, returning the branch taken."""
    body = {
        "fixed": '''
hits=$(grep -c "PAT" "$LOG" 2>/dev/null || true)
case "$hits" in
  ''|*[!0-9]*) echo MALFORMED ;;
  0) echo OK ;;
  *) echo VIOLATION ;;
esac
''',
        "broken": '''
hits=$(grep -c "PAT" "$LOG" 2>/dev/null || echo 0)
if [ "$hits" -gt 0 ] 2>/dev/null; then echo VIOLATION; else echo OK; fi
''',
        "broken_eq": '''
hits=$(grep -c "PAT" "$LOG" 2>/dev/null || echo 0)
if [ "$hits" -eq 0 ] 2>/dev/null; then echo OK; else echo VIOLATION; fi
''',
    }[style]
    script = f'LOG="$1"\n{body}'
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as fh:
        fh.write("".join("PAT hit\n" for _ in range(count_lines)) or "nothing here\n")
        path = fh.name
    try:
        out = subprocess.run(["bash", "-c", script, "_", path],
                             capture_output=True, text=True).stdout.strip()
    finally:
        os.unlink(path)
    return out


def test_fixed_idiom_reports_ok_only_when_the_count_is_really_zero():
    assert _run_case(0, "fixed") == "OK"
    assert _run_case(1, "fixed") == "VIOLATION"
    assert _run_case(67, "fixed") == "VIOLATION"
