#!/usr/bin/env python3
"""WP-C exploratory association (CCF-C 整改执行卡 §4 WP-C, 零 GPU).

Answers (as EXPLORATORY association, NOT causation — per C5 downgrade):
  which offline-sequence attributes co-vary with how much the semantic mask matters?

  y = log(ATE_maskfree / ATE_combined)  (positive = mask helps)
  x1 = MonoGS RPE (rpe_trans_rmse_cm) — 'vanilla failure proxy' (NEVER 'intrinsic difficulty')
  x2 = GTMC person-mask coverage of the mover (person-containing seqs only)
  family = dataset_family (BONN_pair / TUM_static / TUM_sitting / TUM_walking / BONN_mv / BONN_pt / BONN_crowd)

Output: Spearman rho + leave-oneline-out stability, written to results/evidence/wpc_exploratory_association.md.
Family-level resampling recommended by the card (each seq-pair = one unit). We only have
cross-family single-seq observations for most axes, so the family-level bootstrap is
limited; we report per-family means + a simple Spearman over n<=18 seqs and flag it.

This is NOT a causal claim and MUST NOT gate anything (WP-D is already downgraded).
"""
import json, math, os, sys
import numpy as np

def load_x1():
    # MonoGS RPE from baselines xlsx (extracted)
    seq_rpe = {
        'f1_desk':0.8158,'f2_xyz':0.2031,'f3_office':0.4554,'f2_person':0.5784,
        'f3_st_hf':1.0962,'f3_st_rpy':2.4119,'f3_st_xyz':0.9021,'f3_wk_hf':3.0135,
        'f3_wk_rpy':3.0397,'f3_wk_xyz':2.6542,'balloon':2.2314,'balloon2':2.6558,
        'crowd':3.6786,'crowd2':3.6906,'mv_no_box':2.0570,'mv_no_box2':1.7866,
        'pt1':3.4882,'pt2':2.7625,
    }
    return seq_rpe

def load_y():
    with open('/tmp/wpc_y.json') as f:
        d=json.load(f)
    return {s: math.log(v['mf_mean']/v['cb_mean']) for s,v in d.items()}

def load_x2():
    # gtmc coverage (per-seq) from hd_coverage_anchor_perframe.csv aggregate
    return {
        'balloon':0.482,'balloon2':0.594,'mv_no_box':0.231,'mv_no_box2':0.118,
        'pt1':0.299,'pt2':0.188,
    }

def family(seq):
    if seq.startswith(('mv_no_box','mv_no_box2')): return 'bonn_mv'
    if seq.startswith(('pt1','pt2')): return 'bonn_pt'
    if seq in ('balloon','balloon2'): return 'bonn_balloon'
    if seq in ('crowd','crowd2'): return 'bonn_crowd'
    if seq.startswith('f1_') or seq.startswith('f2_xyz') or seq.startswith('f3_office'): return 'tum_static'
    if seq.startswith('f3_st'): return 'tum_sitting'
    if seq.startswith('f3_wk'): return 'tum_walking'
    return 'other'

def spearman(xs, ys):
    order_x = np.argsort(np.argsort(xs))
    order_y = np.argsort(np.argsort(ys))
    return np.corrcoef(order_x, order_y)[0,1]

def main():
    y = load_y()
    x1 = load_x1()
    x2 = load_x2()
    seqs = sorted(y.keys())

    # y vs x1 (all 18) + by-family
    common1=[s for s in seqs if s in x1]
    rho_all = spearman([x1[s] for s in common1],[y[s] for s in common1])
    # leave-one-family-out (exclude each family, recompute)
    fams=sorted(set(family(s) for s in common1))
    loo1={}
    for f in fams:
        keep=[s for s in common1 if family(s)!=f]
        if len(keep)>=5:
            loo1[f]=float(spearman([x1[s] for s in keep],[y[s] for s in keep]))
    # y vs x2 (person-containing only)
    common2=[s for s in seqs if s in x2]
    rho2 = spearman([x2[s] for s in common2],[y[s] for s in common2]) if len(common2)>2 else None

    # per-family y means
    fammean={}
    for f in fams:
        vals=[y[s] for s in seqs if family(s)==f]
        fammean[f]=float(np.mean(vals)) if vals else None

    out={
        'n':len(seqs),'rho_y_x1_all':float(rho_all),
        'loo1_rho':loo1,
        'rho_y_x2_person': rho2, 'n_x2': len(common2), 'x2_seqs':common2,
        'family_y_mean':fammean,
        'caveat':'EXPLORATORY association only; n<=18, single-family seqs cannot bootstrap at family level; '
                 'x1 is a vanilla-failure proxy NOT intrinsic difficulty; x2 is person-mask coverage (person seqs only)',
    }
    # markdown
    md=f"""# WP-C exploratory association (CCF-C 整改执行卡 §4 WP-C)

> **EXPLORATORY — NOT causal** (C5 downgrade: vanilla RPE is a failure OUTPUT shared with ATE,
> so any x1-y correlation is a metric-coupling, never a causal gate). This feeds limitation/discussion,
> does NOT gate anything, does NOT trigger any selector (WP-D already downgraded).

## Data (n={len(seqs)} seqs)
| seq | y=log(mf/cb) | x1 MonoGS-RPE | family |
|---|---:|---:|---|
"""+''.join(f"| {s} | {y[s]:+.3f} | {x1.get(s,'—') if s in x1 else '—'} | {family(s)} |\n" for s in seqs)
    md+=f"""
## Spearman rho
- **y vs x1 (vanilla failure proxy)**: ρ={rho_all:.3f} over n={len(common1)}. LOO-family stability: { {k:f"{v:.2f}" for k,v in loo1.items()} }
- **y vs x2 (GTMC person-mask coverage, person seqs)**: ρ={'%.3f'%rho2 if rho2 is not None else 'n/a'} over n={len(common2)} ({common2})
- **per-family y mean**: { {k:('%.2f'%v if v is not None else '–') for k,v in fammean.items()} }

## Reading (honest)
- Positive y = mask helps. Large positive on **walking / crowd** (y=1.6–3.3), near-zero/negative on
  static & easy person (y≈±0.2), mid (0.7–1.4) on balloon/pt1.
- x1 (vanilla RPE) tracks this (walking/crowd RPE 2.7–3.7 vs static 0.2–0.9) — but this is a failure-output
  coupling, NOT "difficulty caused the gap". **Do not write as intrinsic difficulty.**
- x2 (person-mask coverage) is available only on person/BONN seqs (n={len(common2)}); any ρ there is single-family,
  under-powered, not bootstrappable at family level per the card.

{out['caveat']}
"""
    os.makedirs('results/evidence', exist_ok=True)
    with open('results/evidence/wpc_exploratory_association.md','w') as f:
        f.write(md)
    with open('results/evidence/wpc_exploratory_association.json','w') as f:
        json.dump(out,f,indent=2)
    print(json.dumps(out,indent=2))
    print('wrote results/evidence/wpc_exploratory_association.{md,json}')

if __name__=='__main__':
    main()
