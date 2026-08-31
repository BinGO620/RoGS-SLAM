You are doing an ADVERSARIAL prior-art + soundness review of a research direction. Be blunt; I want the direction killed if it deserves killing. Use web search aggressively for part 1 — that is the most important part.

CONTEXT. Anti-dynamic static 3DGS RGB-D SLAM built on MonoGS (Gaussian Splatting SLAM, Matsuki et al. CVPR 2024). Evaluated on Bonn RGB-D Dynamic + TUM. The map is a set of 3D Gaussians seeded per-pixel from RGB-D keyframes, then optimized by an RGB+depth photometric loss over a sliding keyframe window, with adaptive densification (clone/split) and opacity-based culling. A Mask R-CNN person mask is applied to both insertion and the mapping loss.

THE MEASURED SITUATION.

- The claimed contribution was an ADMISSION-CONTROL policy: pixels whose observed depth conflicts with the current map are held out of the map until confirmed static across keyframes ("deferred"), versus a control that inserts them immediately and deletes them later if contradicted ("prune"). Deferred lost 6/6 sequences on trajectory error and 6/6 on rendering.
- Ledger evidence: both arms reject/expire near-identical candidate counts (same decision engine), but deferred actually inserts ~10x fewer Gaussians because a "the map already explains this" gate kills 80-89% of its confirmed promotions. So the compactness difference is UNDER-SEEDING, not filtering.
- Candidate composition: "background reveal" (observed depth FARTHER than the map renders, i.e. the map holds a stale occluder that is not really there) outnumbers "foreground conflict" by 1.7x-3.8x.
- Forensics from an abandoned attempt show 1,500-5,800 Gaussians per keyframe sitting geometrically IN FRONT of the observed depth surface, on a live map of ~15,000 Gaussians (10-35%). MonoGS's covisibility-based pruning is code-gated to monocular mode only, so under RGB-D the map has NO observation-driven eviction — only opacity culling.

THE PROPOSED NEW DIRECTION.

Observation-contradicted EVICTION: per keyframe, project every live Gaussian into the view; if it sits in front of the observed depth surface by more than a noise band, in a view where the observation is reliable, increment an integer contradiction counter keyed by distinct keyframes; delete the Gaussian at k contradictions. Rationale: dynamic-object residue that the semantic mask leaked is already IN the map, and admission control cannot remove what is already admitted; free-space evidence can.

WHAT I NEED FROM YOU.

1. PRIOR ART — the decisive question. Search the literature hard and tell me whether "delete map primitives contradicted by free-space / ray-casting evidence" is already standard or already published in this exact setting. Cover at minimum:
   (a) 3DGS SLAM: MonoGS, SplaTAM, Gaussian-SLAM, GS-SLAM, Photo-SLAM, LoopSplat, and dynamic variants: DG-SLAM, RoDyn-SLAM, DynaMoN, DynaGSLAM, RGBD-GS-SLAM / RGD-SLAM, and Gaussian dynamic-scene work (Deformable-3DGS, 4DGS) insofar as they do primitive removal.
   (b) NeRF SLAM with explicit removal / free-space supervision: NICE-SLAM, Co-SLAM, ESLAM, Point-SLAM, NeRF-SLAM, and dynamic ones (DynaMoN, RoDynRF).
   (c) The obvious classical ancestor: free-space carving / ray-casting removal in TSDF and occupancy mapping — KinectFusion, Voxblox, Octomap, StaticFusion, Co-Fusion, MaskFusion, EM-Fusion, DynaSLAM, ReFusion (Palazzolo et al.), and removal-by-residual dynamic SLAM work. If ReFusion or StaticFusion already does exactly this in TSDF, say so plainly.
   (d) Anything doing per-primitive "visibility contradiction counting" or "transient primitive removal" in 3DGS specifically (e.g. removing transient/distractor objects from 3DGS reconstructions: SpotLessSplats, NeRF On-the-go, RobustNeRF, Splatfacto-W, WildGaussians, HuGS). This class matters a lot — it may already own the idea.
   Give me: paper, venue/year, what exactly it removes and by what criterion, and a one-line verdict on how much novelty it leaves.

2. SOUNDNESS. Assuming it is not fully pre-empted: what kills contradiction-counted eviction in practice? Be concrete about (i) momentary occlusion of genuinely static structure, (ii) depth-sensor noise at object edges and grazing angles, (iii) camera-pose error placing good Gaussians in front of the observed surface, (iv) the fact that a Gaussian's CENTER projecting in front of the observed depth is not the same as the rendered alpha-composited surface being in front — is center-projection even the right test, or must the test be done in rendered/rasterized space? What does the literature do here?

3. FRAMING. If the mechanism is largely pre-empted, is there a defensible contribution left for a multimedia venue in the *measurement* result instead — namely a controlled demonstration that Gaussian ADMISSION policy is not an effective lever in dense RGB-D 3DGS SLAM (identical filtering, 10x seeding difference, 6/6 loss), with the eviction channel identified as where the headroom actually is? Or is that too thin to publish?

Cite URLs. Say explicitly when you could not verify something rather than guessing.
