# Active Candidate — R1-P01（DRAFT，待 APPROVED）

当前活动候选 = **OpenSet-Deferred**（deferred pre-instantiation lifecycle），
control = **OpenSet-Prune**（insert-then-prune）。二者共享同一 open-set 栈
（ReliabilitySignal + DeferredCommit.reliability_confirm，TriReliability 钉死 off，
CoarsePoseInit 保持 off——probe1 已证伪），唯一允许差异 = `Mapping.lifecycle_mode`，
由 `active/experiment.yaml` 声明并经 contract test 校验。

文件布局：

- `method_openset_prune.yaml` / `method_openset_deferred.yaml`：R1-P01 两臂 method overlay；
- `openset_{prune,deferred}_<真实序列名>.yaml`：成对 per-seq 配置（inherit 序列 base +
  method_from overlay），由 `active/sequences.yaml` 按 `pair`/`arm` 引用；
- `method_combined_maskboth_deferred.yaml`（QUEUED，R1-P03 combined-vs-prune）：
  已按修正后的定义备好（combined 补上 `mask_insertion: true`、不回收 CoarsePoseInit），
  在 manifest 建立前不被任何 registry 引用。

失败 candidate 的配置在结果登记完成后删除（见上级 README 规则）。
