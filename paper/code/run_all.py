"""run_all.py: run every example program and save its stdout under outputs/.

The paper's appendix includes these files verbatim, so the outputs quoted in the text
are the outputs of the code as shipped. simulate.py also writes the two CSV files that
Figures 3 and 4 plot.

Run:  python run_all.py
"""
import subprocess, sys, warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
SCRIPTS = ["attested_rpc.py", "orchestrator.py", "lifecycle.py", "simulate.py"]

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name in SCRIPTS:
        r = subprocess.run([sys.executable, "-W", "ignore", name], cwd=HERE,
                           capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"{name} failed:\n{r.stderr}")
        (OUT / name.replace(".py", ".txt")).write_text(r.stdout, encoding="utf-8")
        print(f"== {name}\n{r.stdout}")
