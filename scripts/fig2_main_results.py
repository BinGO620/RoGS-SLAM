#!/usr/bin/env python3
"""Fig 2 (主结果) — ALL 18/18 run removal % vs dPSNR scatter.
Data: R3-P05 step5b 3seed table (balloon, mv_no_box, pt1, pt2) + p4_op001_full18.md
(balloon2, mv_no_box2). Y in micro-dB so the near-zero cloud is visible; the single worst
point (−0.0025 dB = −250 micro-dB, mv_no_box2 seed0) is the only one that leaves the band.
"""
import os, matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
# seq -> list of (rm%, dPSNR) per seed, all 6 seqs × 3 seeds = 18 points
data = {
    "balloon":   [(12.8,-0.0001),(18.4,-0.0001),(17.3,+0.0001)],
    "mv_no_box": [(9.9,+0.0000),(8.4,-0.0000),(10.0,-0.0001)],
    "pt1":       [(9.9,+0.0000),(10.1,-0.0000),(10.3,+0.0000)],
    "pt2":       [(18.4,-0.0000),(11.2,+0.0000),(10.5,+0.0000)],
    "balloon2":  [(11.4,-0.0000),(8.8,-0.0000),(11.2,-0.0000)],
    "mv_no_box2":[(9.6,-0.0025),(12.7,-0.0003),(13.0,-0.0001)],
}
fig,ax=plt.subplots(figsize=(5.5,4))
for seq,pts in data.items():
    x=[p[0] for p in pts]; y=[p[1]*1e6 for p in pts]   # micro-dB = dB×10^6
    ax.scatter(x,y,label=seq,s=60)
ax.axhline(0,color="black",lw=0.8)
ax.set_xlabel("op<0.01 removal %")
ax.set_ylabel(r"$\Delta$PSNR ($\mu$dB)")
ax.set_title("Terminal pruning: 18/18 self-tracked maps" )
# inset: full dB-scale view so the cloud's near-zero band and the sole worst point are both legible
axins=ax.inset_axes([0.12,0.10,0.42,0.42])
for seq,pts in data.items():
    x=[p[0] for p in pts]; y=[p[1] for p in pts]
    axins.scatter(x,y,s=24)
axins.axhline(0,color="black",lw=0.6)
axins.set_title("full dB scale",fontsize=7)
axins.set_xlabel("removal %",fontsize=7); axins.set_ylabel(r"$\Delta$PSNR (dB)",fontsize=7)
axins.tick_params(labelsize=6)
ax.legend(frameon=False,fontsize=8,loc="upper left"); ax.grid(ls=":",alpha=0.4)
os.makedirs("papers/mmm/figures",exist_ok=True)
fig.tight_layout(); fig.savefig("papers/mmm/figures/fig2_main_results.png",dpi=150)
print("wrote fig2_main_results.png (18/18 runs)")
