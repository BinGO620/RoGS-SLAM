import glob, os, sys
from pathlib import Path
sys.path.insert(0, "/data/monogs-ours")
os.chdir("/data/monogs-ours")
from gaussian_splatting.scene.gaussian_model import GaussianModel
from munch import munchify
import yaml, torch, numpy as np, time

def run_savings(ply, run_root):
    cfg = yaml.safe_load(open(Path(run_root)/"config.yml"))
    mp = munchify(cfg["model_params"]); mp.sh_degree = 3 if cfg["Training"]["spherical_harmonics"] else 0
    g = GaussianModel(mp.sh_degree, config=cfg); g.load_ply(str(ply))
    n = int(g.get_xyz.shape[0])
    sig = torch.sigmoid(g._opacity).reshape(-1)
    keep = sig >= 0.01
    n_rm = int((~keep).sum())
    out = Path("/tmp/p3_art_savings"); out.mkdir(exist_ok=True)
    o0 = out/"orig.ply"; o1 = out/"pruned.ply"
    g.save_ply(str(o0))
    g2 = GaussianModel(mp.sh_degree, config=cfg); g2.load_ply(str(ply))
    g2._prune_raw(keep.to(g2.get_xyz.device))
    g2.save_ply(str(o1))
    b0 = o0.stat().st_size; b1 = o1.stat().st_size
    print(f"  {Path(ply).parent.parent.name:16s} N={n:6d} rm={n_rm:5d} ({n_rm/max(n,1)*100:.1f}%)  bytes {b0/1e6:5.2f}MB -> {b1/1e6:5.2f}MB  (saved {100*(1-b1/b0):4.1f}%)")

for seq in ["balloon","balloon2","mv_no_box"]:
    for cand in glob.glob(f"results/runs/P3/P3-DENSIFY-TAIL/{seq}_base_seed0/**/point_cloud/final_after_opt/point_cloud.ply", recursive=True):
        run_root = cand.split("/point_cloud/")[0]
        run_savings(cand, run_root)
        break
