#!/usr/bin/env python3
"""WP-D0' descriptive probe (CCF-C 整改执行卡 §4 WP-D action 2, 零 GPU).

PURPOSE: support ONE honest future-work sentence — 'we examined several online-obtainable
statistics, but the current sequence count is insufficient to validate any discrimination
rule'. It is NOT a fit, NOT a LOO, NOT a gate, NOT a claim. n=4 (1 both-optimal, 3 geo-optimal)
— any separation from a lever is statistically indistinguishable from chance.

FROZEN features (≤5) from P7 runs, from the FIRST 10% of frames only, WITHOUT loading
tracking_raw (script-level isolation against label leakage):
  pose_variability : std of per-frame translation increments over first 10% frames
                     (from groundtruth for the sequence — geometric stats only, not the
                     tracker's own RPE which is endogenous/feedback).
  valid_depth_rate  : fraction of depth pixels > 0.01 over first 10% frames.
  median_flow_mag   : median |f_obs| (backward RAFT) over first 10% frames.
  flow_valid_rate   : mean flow_valid_frac over first 10% frames.
  geom_anomaly_p90  : p90 of g_mean over first 10% frames.
The 'optimal cue' per sequence comes from the P7 3-seed verdict (BOTH for mv_no_box,
GEOMETRY for balloon / mv_no_box2 / pt2).
"""
import csv, glob, json, os
import numpy as np

FEATURES = ["pose_variability", "valid_depth_rate", "median_flow_mag", "flow_valid_rate", "geom_anomaly_p90"]
P7_ROOT = "results/runs/P7/P7-CUESPLIT"
# seq -> optimal cue from p7_cuesplit_verdict (n=4, 1 both-opt, 3 geo-opt)
OPTIMAL = {"mv_no_box": "both", "mv_no_box2": "geo", "pt2": "geo", "balloon": "geo"}
SEQ_TOTAL = {"mv_no_box": 778, "mv_no_box2": 931, "pt2": 567, "balloon": 439}


def first10(parsed, total):
    k = max(int(total * 0.1), 2)
    return parsed[:k]


def load_frozen(seq):
    """Collect frame features from flow_raft + depth, first 10% frames."""
    total = SEQ_TOTAL[seq]
    seqdir_map = {"mv_no_box": "rgbd_bonn_moving_nonobstructing_box",
                  "mv_no_box2": "rgbd_bonn_moving_nonobstructing_box2",
                  "pt2": "rgbd_bonn_person_tracking2", "balloon": "rgbd_bonn_balloon"}
    d = f"/data/Datasets/Bonn/{seqdir_map[seq]}"
    # pose_variability from groundtruth
    gt = np.loadtxt(f"{d}/groundtruth.txt", comments="#")[:, 1:8]  # tx ty tz qx qy qz qw
    trans = gt[:, :3]
    diffs = np.diff(trans, axis=0)
    pv = np.std(np.linalg.norm(diffs, axis=1)[:max(int(total*0.1),2)])
    # median_flow_mag from flow_raft (backward |f_obs|) first 10%
    flow_files = sorted(glob.glob(f"{d}/flow_raft/*.npy"))
    mags = []
    for fp in flow_files[:max(int(total*0.1),2)]:
        f = np.load(fp)  # (H,W,2)
        mags.append(np.median(np.sqrt((f[...,0]**2 + f[...,1]**2))))
    med_flow = float(np.median(mags)) if mags else None
    # valid_depth_rate + flow_valid_rate + geom_anomaly_p90 from reliability_signal frames.csv
    frames_csv = sorted(glob.glob(f"{P7_ROOT}/cuesplit_{seq}_geo_seed0/**/reliability_signal/frames.csv", recursive=True))
    fv = flow_valid = geom = None
    if frames_csv:
        rows = list(csv.DictReader(open(frames_csv[0])))
        head = first10(rows, total)
        flow_valid = [float(r["flow_valid_frac"]) for r in head]
        geom = [float(r["g_mean"]) for r in head]
        valid_depth = None  # not in frames.csv; compute from depth below
    # valid_depth_rate from depth files first 10%
    dep_files = sorted(glob.glob(f"{d}/depth/*.png"))

    def _dep_rate(fp):
        try:
            from PIL import Image
            a = np.asarray(Image.open(fp))
            return float((a > 5).sum() / a.size)  # depth_scale 5000 => >0.001m
        except Exception:
            return None
    rates = [_dep_rate(fp) for fp in dep_files[:max(int(total*0.1),2)]]
    rates=[r for r in rates if r is not None]
    valid_depth = float(np.mean(rates)) if rates else None

    return {
        "pose_variability": float(pv),
        "valid_depth_rate": valid_depth,
        "median_flow_mag": med_flow,
        "flow_valid_rate": float(np.mean(flow_valid)) if flow_valid else None,
        "geom_anomaly_p90": float(np.percentile(geom, 90)) if geom else None,
    }


def main():
    table = {}
    for seq, opt in OPTIMAL.items():
        table[seq] = {"optimal_cue": opt, **load_frozen(seq)}
    # render markdown
    md = "# WP-D0′ descriptive probe（CCF-C 整改执行卡 §4 WP-D action 2，零 GPU）\n\n"
    md += "> **只做描述性报告，不拟合、不 LOO、不产生 GO 分支。** 用途 = 支撑一句诚实的 future-work 表述：\n"
    md += "> *“我们检查了若干在线可得的统计量，但当前序列数（n=4，1 正 3 负）不足以验证任何判别规则”。*\n"
    md += "> 任何分离（无论看起来多像规律）都与偶然无法区分，**不得**据此声称找到 regime 信号。\n\n"
    md += "| seq | optimal cue | pose_var | valid_depth% | median_flow | flow_valid% | geom_p90 |\n"
    md += "|---|---|---:|---:|---:|---:|---:|\n"
    for seq in sorted(table):
        r = table[seq]
        md += (f"| {seq} | {r['optimal_cue']} | {r['pose_variability']:.4f} | "
               f"{(r['valid_depth_rate'] or 0)*100:.1f}% | {r['median_flow_mag'] or 0:.2f} | "
               f"{(r['flow_valid_rate'] or 0)*100:.1f}% | {r['geom_anomaly_p90'] or 0:.3f} |\n")
    md += "\n## 读（唯一允许的结论）\n\n"
    md += f"> **n=4（1 个 both-优 + 3 个 geometry-优），任何判别规则的验证在样本量上不可行。**\n"
    md += "> 因此 regime detector 明确降级为 future work。若将来要做（下一个/下一轮前置条件）：需要\n"
    md += "> ≥8–10 个序列覆盖两类 regime、外部指定/理论推导的规则（不从结果里搜）、以及在最终方法上重跑 WP-A/B 的预算。\n"
    os.makedirs("results/evidence", exist_ok=True)
    open("results/evidence/wpd0_descriptive_probe.md","w").write(md)
    json.dump(table, open("results/evidence/wpd0_descriptive_probe.json","w"), indent=2)
    print(json.dumps(table, indent=2))
    print("wrote results/evidence/wpd0_descriptive_probe.{md,json}")


if __name__ == "__main__":
    main()
