#!/usr/bin/env python3
"""Fig 4 (承重图) — matched-rate deletion controls across ALL 6 sequences, rates 5% & 10%.

Data: p3_matched_rate_extended.md (18 P2-T prune maps, 3-seed aggregate, random 10 draws ±CI).
Plot: grouped bar of GTdPSNR for low/high/random at matched removal, per seq, 10% rate (the headline one).
"""
import os, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# seq: low, high, random_mean (±sd) at 10%  (from final table)
data = {
    "balloon":   ( +0.0000, -5.05, -0.90, 0.35),
    "balloon2":  (-0.0001, -3.65, -0.47, 0.14),
    "mv_no_box": (-0.0002, -4.34, -0.87, 0.20),
    "mv_no_box2":(-0.0007, -4.30, -1.04, 0.38),
    "pt1":       ( +0.0000, -3.96, -0.87, 0.16),
    "pt2":       ( +0.0000, -4.38, -1.00, 0.24),
}
seqs=list(data.keys())
low=[data[s][0] for s in seqs]; high=[data[s][1] for s in seqs]
rm=[data[s][2] for s in seqs]; rsd=[data[s][3] for s in seqs]

x=np.arange(len(seqs)); w=0.25
fig,ax=plt.subplots(figsize=(8,4.2))
ax.bar(x-w, high, w, color="#d62728", label="high-opacity deletion")
ax.bar(x,   rm,   w, color="#ff7f0e", yerr=[rsd]*1, label="random deletion (mean±sd, 10 draws)")
ax.bar(x+w, low,  w, color="#2ca02c", label="low-opacity deletion (ours)")
ax.axhline(0,color="black",lw=0.8)
ax.set_ylabel(r"$\Delta$PSNR (dB), matched 10% removal, 3-seed mean")
ax.set_xticks(x); ax.set_xticklabels(seqs, rotation=15)
ax.set_title("Terminal pruning is specifically safe: low-opacity cohort at $\\approx$0 dB vs random/high-op")
ax.legend(frameon=False); ax.grid(axis="y",ls=":",alpha=0.4)

# value labels on the low-opacity bars (all ≈0, near-invisible on the −6.5..+0.6 axis):
for xi, lo in zip(x+w, low):
    ax.text(xi, 0.05, f"{lo:+.4f}", ha="center", va="bottom", fontsize=8, color="#1a7a1a", rotation=0)

# zoomed inset on low & random at a scale that actually captures BOTH series
# random values ±sd reach −1.42 → y-range must extend below that so no error bar is clipped:
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
axin = inset_axes(ax, width="42%", height="40%", loc="center right", borderpad=1.2)
axin.bar(x+w, low,  w, color="#2ca02c", label="low")
axin.bar(x,   rm,   w, color="#ff7f0e", yerr=[rsd]*1, label="random")
axin.axhline(0,color="black",lw=0.6)
axin.set_ylim(-1.45, 0.02)   # capture the full random incl. worst −1.42 (no clipping); low bars hug 0
axin.set_title("zoomed: low (green) vs random (orange)", fontsize=7)
axin.tick_params(labelsize=6)
for t in axin.get_xticklabels(): t.set_rotation(45); t.set_ha('right')
for lbl in axin.get_yticklabels(): lbl.set_visible(False)  # declutter inset y-axis labels

ax.set_ylim(-6.5, 0.6)
fig.tight_layout()
os.makedirs("papers/mmm/figures",exist_ok=True)
fig.savefig("papers/mmm/figures/fig4_matched_rate.png",dpi=150)
print("wrote fig4_matched_rate.png (all 6 seqs, 10% rate, random±sd CI, low-op visible via labels+zoom inset)")
