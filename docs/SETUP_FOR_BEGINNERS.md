# Setup for absolute beginners — where do I even type these commands?

You've never used a terminal, pip, or Jupyter? This page is the bridge.
Ten minutes, once, and every command in this repo will make sense.

## 1. Open a terminal (that's where commands go)

- **Windows**: press the Windows key, type `cmd`, hit Enter. The black
  window that opens is the "Command Prompt" — that's your terminal.
  (Anywhere our docs say "bash", Command Prompt works the same for our
  commands.)
- **Mac**: press Cmd+Space, type `Terminal`, hit Enter.

## 2. Check you have Python

Type this in the terminal and press Enter:

```
python --version
```

If you see `Python 3.10` or higher, you're set. If not, install it from
https://www.python.org/downloads/ (check "Add python.exe to PATH" on the
first installer screen — that checkbox matters).

## 3. Install the tool

```
pip install cbi-plus
```

`pip` is Python's app store; this one line downloads the package **and**
everything it needs (NumPy, pandas — you don't install those yourself).
(If you cloned this repo instead, run `pip install -e .` from the repo
folder — `-e .` means "install from this folder, the dot is the folder".)

## 4. Prove it works (no data needed)

```
python -c "from cbi_pipeline import api; api.verify_installation()"
```

You should see a few lines ending in `verify_installation: PASS`. That ran
a full simulated-corridor diagnosis on your machine.

## 5. Open your first notebook

The teaching notebooks are `.ipynb` files — **a browser or double-click
shows raw code; you need a notebook app**. Easiest path:

1. Install [VS Code](https://code.visualstudio.com/) (free).
2. In VS Code: File → Open Folder → this repo.
3. Click `notebooks/01_getting_started.ipynb` — VS Code offers to install
   the Python/Jupyter extensions; say yes.
4. Click "Run All" at the top. Plots appear under the cells.

(Alternative: `pip install jupyter` then type `jupyter lab` in the
terminal from the repo folder — a browser tab opens; click the notebook.)

## 6. What the jargon means (30 seconds)

| word | meaning |
|---|---|
| terminal / command prompt / "bash" | the window where you type commands |
| pip | Python's package installer |
| venv | an isolated Python sandbox so projects don't interfere — optional for you at this stage |
| clone the repo | download this project's folder from GitHub (green "Code" button → Download ZIP works fine) |
| notebook / Jupyter | an interactive document that mixes text, code, and plots |
| AMS | Analysis, Modeling & Simulation — the umbrella term for traffic modeling workflows |

Next stop: [the Glossary](GLOSSARY.md) (5 minutes — every traffic symbol
we use), then [notebook 01](../notebooks/01_getting_started.ipynb).
