# Contributing

Thanks for your interest. This repository accompanies an academic paper and is
maintained on a best-effort basis.

## Reporting a problem

Open an issue using the template in `.github/ISSUE_TEMPLATE/`. Please include:

1. The exact command you ran.
2. The full error text (not a paraphrase).
3. `nvidia-smi`, `nvcc --version`, and `conda list | grep -E "torch|numpy"`.
4. Whether the failure is on a smoke run (`--max-frames 40`) or a full run.

Without this information a reproduction failure usually cannot be diagnosed.

## Pull requests

- Keep changes scoped: one logical change per PR.
- Do not reformat unrelated files.
- If you change a mechanism or a config default, state which paper number is
  affected and attach the before/after readings.
- Run the test suite before submitting:
  `pytest tests -q` (see `REPRODUCING.md` for the exact subset per repo).

## Scope

This is a reproducibility release, not a general-purpose SLAM framework. Feature
requests outside the paper's scope will usually be closed.

## License

By contributing you agree that your contribution is released under the
non-commercial research terms in [LICENSE](LICENSE).
