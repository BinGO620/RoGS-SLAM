#!/usr/bin/env python3
"""Fig 3 (机制图) — opacity tail: online final vs refine-after (final_after_opt) + frozen-opacity.

Headline mechanism statement (codex R5, 2026-08-09): the cohort fraction RISES 36/36 after
refinement; it does NOT "appear only after". Downgraded title + Y-label value accordingly.
REAL per-run data (from p3_terminal_mech_autopsy.md §1 subtable) + frozen-opacity intervention
(p3_terminal_refine_freeze_result.md §2a, balloon prune seed0). Both framed as supporting,
NOT causal.
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# seq -> (online %, after %)  -- sigmoid-opacity <0.01 tail fraction, per p3_terminal_mech_autopsy.md §1
per_run = [
    ("balloon-s0",   1.8, 12.8),
    ("balloon-s1",   4.9, 18.4),
    ("balloon2-s0",  0.0, 11.4),
    ("mv_no_box-s0", 1.5,  9.9),
    ("pt1-s0",       0.0,  9.9),
    ("pt2-s0",       2.2, 18.4),
]
# 36-run aggregate (P2-T): online 0.69% -> after 10.39% (mean +9.69pp, 36/36 growth)
agg_online, agg_after = 0.69, 10.39
NAMES = [p[0] for p in per_run]
ONLINE = [p[1] for p in per_run]
AFTER  = [p[2] for p in per_run]

# frozen-opacity counterfactual (balloon prune seed0, identity-matched): std 1.79->12.79 (after_opt),
# freeze 4.09->3.68. The "after_opt" number is the headline: std 12.8 vs freeze 3.7.
fr_std, fr_freeze = 12.8, 3.68

def main():
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.9))

    # --- left: per-run online vs after (paired) ---
    ax = axes[0]
    rng = np.random.default_rng(0)
    jitter = rng.uniform(-0.18, 0.18, len(ONLINE))
    ax.plot([0, 1], np.stack([ONLINE, AFTER], axis=0), alpha=0.55, lw=1, color="tab:gray", zorder=1)
    ax.scatter(np.zeros(len(ONLINE)) + jitter, ONLINE, color="tab:blue", s=45, zorder=3, label="online `final`")
    ax.scatter(np.ones(len(AFTER))  + 0 + jitter, AFTER,  color="tab:red",  s=45, zorder=3, label="after refinement")
    # 36-run aggregate markers (filled stars, right column only for clarity at the online anchor)
    ax.plot([0, 1], [agg_online, agg_after], color="black", lw=2, ls="--", zorder=2,
            label="36-run mean (+9.7pp)")
    ax.set_xticks([0, 1]); ax.set_xticklabels(["online\n`final`", "after\nrefinement"], rotation=20)
    ax.set_ylabel(r"Gaussians with sigmoid(op) $<10^{-2}$ (%)")
    ax.set_title("Tail fraction grows after refinement\n(6 P2-T runs; online 0-4.9% -> after 9.9-18.4%)")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    ax.grid(ls=":", alpha=0.4)

    # --- right: frozen-opacity counterfactual ---
    ax = axes[1]
    bars = ax.bar([0, 1], [fr_std, fr_freeze], color=["#d62728", "#7f7f7f"], width=0.55)
    bars[0].set_label("std refine (opacity free)")
    bars[1].set_label("freeze opacity")
    ax.axvline(0.5, color="k", lw=0.6, ls=":")
    ax.text(0.0, 5.2, "12.8%", ha="center", fontsize=10, color="#d62728")
    ax.text(1.0, 1.2, "3.7%", ha="center", fontsize=10, color="#7f7f7f")
    ax.set_xticks([0, 1]); ax.set_xticklabels(["std", "freeze"], rotation=0)
    ax.set_ylim(0, 13.8)
    ax.set_ylabel(r"Gaussians with sigmoid(op) $<10^{-2}$ (%)")
    ax.set_title("Opacity-freeze intervention\n(confounded: runs differ pre-refinement; see text)")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(axis="y", ls=":", alpha=0.4)

    fig.tight_layout()
    os.makedirs("papers/mmm/figures", exist_ok=True)
    # Write the real figure; keep no PLACEHOLDER suffix (this is now a real figure).
    fig.savefig("papers/mmm/figures/fig3_mechanism.png", dpi=150)
    print("wrote fig3_mechanism.png (real per-run data; opacity-freeze title downgraded to 'intervention')")

if __name__ == "__main__":
    main()
