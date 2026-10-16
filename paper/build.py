"""
Build the paper PDF: (optionally run the code) -> lualatex -> biber -> lualatex x2.

Usage (from anywhere):
    python paper/build.py            # build from existing code outputs
    python paper/build.py --run      # re-run code/run_all.py first (needs the Python deps)
Needs MiKTeX or TeX Live with LuaLaTeX + Biber. Output: paper/main.pdf.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MIKTEX = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/MiKTeX/miktex/bin/x64"


def run(cmd, cwd=HERE):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        log = (HERE / "main.log").read_text(encoding="utf-8", errors="replace") if cmd[0] == "lualatex" else r.stdout + r.stderr
        errs = [l for l in log.splitlines() if l.startswith("!")]
        sys.exit(f"{cmd[0]} failed:\n" + "\n".join(errs[:10] or log.splitlines()[-25:]))


def main():
    if "--run" in sys.argv:
        run([sys.executable, "run_all.py"], cwd=HERE / "code")
    if shutil.which("lualatex") is None and MIKTEX.exists():
        os.environ["PATH"] = str(MIKTEX) + os.pathsep + os.environ["PATH"]
    tex = ["lualatex", "-interaction=nonstopmode", "-halt-on-error", "main.tex"]
    run(tex); run(["biber", "main"]); run(tex); run(tex)
    log = (HERE / "main.log").read_text(encoding="utf-8", errors="replace")
    undefined = sorted(set(re.findall(r"(?:Reference|Citation) `?'?([^' ]+)'? on page \d+ undefined", log)))
    missing = sorted(set(re.findall(r"Missing character: There is no (\S+)", log)))
    overfull = re.findall(r"Overfull \\hbox \(([\d.]+)pt too wide\)", log)
    pages = re.search(r"Output written on main\.pdf \((\d+) pages", log)
    blg = (HERE / "main.blg").read_text(encoding="utf-8", errors="replace")
    print(f"main.pdf: {pages.group(1) if pages else '?'} pages")
    print("undefined references/citations:", undefined or "none")
    print("missing characters:", missing or "none")
    print("biber warnings:", len(re.findall(r"WARN", blg)))
    big = [float(x) for x in overfull if float(x) > 2]
    print(f"overfull boxes > 2 pt: {len(big)}" + (f" (largest {max(big):.1f} pt)" if big else ""))


if __name__ == "__main__":
    main()
