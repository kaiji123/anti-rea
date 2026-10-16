# SA-HEACS paper

LaTeX source, code and data for *SA-HEACS: Server-Assisted Hybrid Execution and
AI-Optimized Cloud Shielding Against Automated Reverse Engineering*.
`SA-HEACS-paper.pdf` is the original draft; `paper/main.pdf` is the typeset version.

```
paper/
  main.tex, sections/*.tex      paper source (LuaLaTeX, biblatex-ieee, Biber)
  figures/*.tex                 TikZ figures 1-2 (figures 3-4 are pgfplots, drawn from the CSVs)
  references.bib                bibliography (DOIs checked against Crossref, 2026-10-16)
  build.py                      lualatex -> biber -> lualatex x2, then a problem summary
  code/
    attested_rpc.py             Algorithm 1: attested, encrypted RPC (FastAPI + cryptography)
    orchestrator.py             Algorithms 2-4: locality router, micro-batcher, Markov prefetch
    lifecycle.py                Algorithm 5: tier promotion/demotion over one simulated year
    simulate.py                 Section 8 SimPy model -> results_batching.csv, results_prefetch.csv
    run_all.py                  runs all four, saves stdout to code/outputs/ (quoted in the appendix)
    requirements.txt
```

## Reproduce

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -r paper/code/requirements.txt   # Windows path; bin/ on Unix
.venv/Scripts/python paper/code/run_all.py      # regenerates outputs/ and the CSVs
python paper/build.py                           # needs MiKTeX or TeX Live (LuaLaTeX + Biber)
```

The appendix includes the `.py` files and `code/outputs/*.txt` directly, and Figures 3-4 and
Table 3 read the CSVs, so a rebuild after `run_all.py` always matches the code.
