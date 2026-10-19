# Changelog

Each release of ThermaSched: the cleaning notebook (`data_prep.ipynb`), the solver and batch
notebooks (`solver.ipynb`, `batch.ipynb`) and the site. The notebooks print their release when
they run, every scenario and run records it, and the site shows it in the sidebar and on each
run.

**Re-run** says what to do after replacing the notebooks with a new release:

- **Nothing:** only the site or the documentation changed. Existing runs stay valid.
- **Solver:** the model changed. Solve again the runs you want to compare with new ones; runs
  from the earlier release still open on the site, marked with their release.
- **Cleaning, then solver:** the scenarios changed. Run the cleaning notebook again (its
  section 4 shows which scenarios differ from before), then solve again. The site warns when
  a run was solved on a different scenario build than the one it holds.

## 1.0.0 (2026-10-19)

First release to the thesis group.

**Re-run:** everything, from the raw data: the cleaning notebook, then the solver or batch
notebook.

- Cleaning notebook: builds the main scenario `thesis10`, the experiments `consolidated6`,
  `thesis10_tight`, `thesis10_swing`, `thesis10_warm`, the test scenario `small`, and
  `small_running` (`small` with running workloads and a server outage). It checks the raw file
  sizes and compares every scenario it writes with the reference scenarios of the release.
- Solver notebook: one run, step by step, with a scenario of your own if wanted.
- Batch notebook: a list of runs, unattended, preset to the thesis scenarios; resumes after a
  disconnect and writes one zip for the site.
- Every run records the release, where it was made, and a fingerprint of its scenario. Run
  names hold every switch that differs from its default, so a sweep (for example over
  `H_min_C`) never overwrites its own runs.
