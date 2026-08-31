#!/usr/bin/env python3
"""Aggregate our full-frame rendering columns (PSNR/SSIM/LPIPS/depth) + our ATE from
tracking_raw, ready to splice into the 18-seq main rendering table.

Reads posthoc_fullframe/fullframe_summary.json produced by the remote 3090 batch
(run from final/ PLY + trj_full_final) and tables/tracking_raw.csv ate_rmse_cm.

Run AFTER results/runs/.../posthoc_fullframe/*.json are synced back. Emits a compact
per-seq mask-free / mask-ON 3-seed mean±std table to stdout.

18-seq sheet names (xlsx) vs our internal names:
  f1_desk f2_xyz f3_office f2_person f3_st_hf f3_st_rpy f3_st_xyz
  f3_wk_hf f3_wk_rpy f3_wk_xyz balloon balloon2 crowd crowd2
  mv_no_box mv_no_box2 pt1(pt=person_t) pt2(person_t2)
"""
import glob, os, statistics, json

ROOT = "results/runs"

# seq -> list of (ts_dir, method_kind) where kind in {'maskfree','maskon'}
def discover():
    out = {}  # seq -> {'maskfree': {seed: tsdir}, 'maskon': {seed: tsdir}}
    # P6-MASON is the canonical mask-ON (crowd/crowd2/f3_wk_rpy/f3_wk_xyz/pt1). P2-T_3090
    # *_prune is the canonical mask-ON for the other 5 BONN (balloon/balloon2/mv_no_box/
    # mv_no_box2/pt2). pt1 appears in BOTH P6-MASON (canonical) and P2-T_3090; prefer
    # P6-MASON for pt1 so the 3-seed mean is a single run config only.
    P6MASON_COMBINED = {"crowd", "crowd2", "f3_wk_rpy", "f3_wk_xyz", "pt1"}
    roots = {
        "results/runs/P6/P6-18SEQ/*": "maskfree",
        "results/runs/P6/P6-MASKOFF-3SEED/*": "maskfree",
        "results/runs/P6/P6-MASKOFF/*": "maskfree",
        "results/runs/P2/P2-T_3090/*_prune_seed*": "maskon",
        "results/runs/P6/P6-MASON/*": "maskon",
        "results/runs/P6/P6-MASON-8SEQ/*": "maskon",
        # missing8 combined(mask-ON) backfill: f1_desk/f2_xyz/f3_office/f2_person/
        # f3_st_{hf,rpy,xyz}/f3_wk_hf x3 seed (P6-MASON-8SEQ). These seqs are NOT in
        # P6MASON_COMBINED so there is no src-conflict with P2-T_3090.
        "results/runs/P6/P6-MASON-8SEQ/*_combined_seed*": "maskon",
    }
    for pat, kind in roots.items():
        for d in glob.glob(pat):
            if not os.path.isdir(d) or "consolelog" in os.path.basename(d):
                continue
            base = os.path.basename(d)
            m = base.rsplit("_seed", 1)
            if len(m) != 2:
                continue
            runname, seed = m[0], m[1]
            seq = None
            src = None
            if "_maskoff" in runname:
                seq = runname.replace("_maskoff", ""); src = "P6-MASKOFF"
            elif "_prune" in runname:
                seq = runname.replace("_prune", ""); src = "P2-T-3090"
            elif "_combined" in runname:
                seq = runname.replace("_combined", ""); src = "P6-MASON"
            else:
                continue
            # mask-ON: if this seq is canonical-P6MASON and this dir is the non-canonical
            # P2-T_3090 source, skip (P6-MASON wins for pt1).
            if kind == "maskon" and seq in P6MASON_COMBINED and src == "P2-T-3090":
                continue
            # latest complete ts dir
            latest = None
            for ts in glob.glob(d + "/datasets_*/*/seed_*/*/"):
                ts = ts.rstrip("/")
                if not os.path.isfile(ts + "/config.yml"):
                    continue
                if not os.path.exists(ts + "/posthoc_fullframe/fullframe_summary.json"):
                    continue
                if latest is None or ts > latest:
                    latest = ts
            if latest is None:
                continue
            out.setdefault(seq, {}).setdefault(kind, {})[seed] = latest
    return out

def agg_mean(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    m = statistics.mean(vals)
    if len(vals) > 1:
        return (round(m, 4), round(statistics.stdev(vals), 4))
    return (round(m, 4), None)

def read_summary(tsd):
    p = os.path.join(tsd, "posthoc_fullframe", "fullframe_summary.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p) as f:
            return json.load(f).get("fullframe", {})
    except Exception:
        return None

def read_ate(tsd):
    # ts = <results/runs/GROUP>/<runname>/datasets_X/<cfgname>/seed_N/2026-...
    # run root = up 5: [.., GROUP, runname, datasets_X, cfgname, seed_N, 2026]
    parts = tsd.split(os.sep)
    runroot = os.sep.join(parts[:-6])
    csvpath = os.path.join(runroot, "tables", "tracking_raw.csv")
    if not os.path.isfile(csvpath):
        return None
    with open(csvpath) as f:
        hdr = f.readline().rstrip("\n").split(",")
        cols = [c.strip() for c in hdr]
        if "ate_rmse_cm" not in cols:
            return None
        i = cols.index("ate_rmse_cm")
        vals = []
        for line in f:
            row = line.rstrip("\n").split(",")
            if len(row) <= i: continue
            try:
                vals.append(float(row[i]))
            except ValueError:
                pass
        if not vals:
            return None
        m = statistics.mean(vals)
        return (round(m,4), round(statistics.stdev(vals),4)) if len(vals)>1 else (round(m,4),None)

def main():
    disc = discover()
    seqorder = ["f1_desk","f2_xyz","f3_office","f2_person","f3_st_hf","f3_st_rpy",
                "f3_st_xyz","f3_wk_hf","f3_wk_rpy","f3_wk_xyz","balloon","balloon2",
                "crowd","crowd2","mv_no_box","mv_no_box2","pt1","pt2"]
    print("seq | mask-free PSNR/SSIM/LPIPS/depth | mask-ON PSNR/SSIM/LPIPS/depth")
    for seq in seqorder:
        if seq not in disc:
            print(f"{seq}: NO disc"); continue
        row = {}
        for kind in ("maskfree","maskon"):
            if kind not in disc[seq]:
                row[kind] = "—"
                continue
            stats_d = {k: [] for k in ("psnr","ssim","lpips","depth_l1_cm")}
            ates = []
            for seed, tsd in sorted(disc[seq][kind].items()):
                ff = read_summary(tsd)
                if not ff: continue
                for k in stats_d:
                    stats_d[k].append(ff.get(k))
                ates.append(read_ate(tsd))
            fmt = []
            for k in ("psnr","ssim","lpips","depth_l1_cm"):
                a = agg_mean(stats_d[k])
                if a is None: fmt.append("—"); continue
                m, s = a
                fmt.append(f"{m}" if s is None else f"{m}±{s}")
            row[kind] = " / ".join(fmt)
        print(f"{seq:10s} | {row['maskfree']:42s} | {row['maskon']}")

if __name__ == "__main__":
    main()
