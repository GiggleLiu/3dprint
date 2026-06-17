# 🧪 Hydrogen Molecule 3D Model Generator

A Python project to create 3D printable molecular models, starting with the simplest molecule: **Hydrogen (H₂)**.

## 🎯 What This Creates

This script generates an STL file of a hydrogen molecule consisting of:
- **Two spheres** representing hydrogen atoms
- **A cylinder** representing the covalent bond

The model is ready for 3D printing in standard slicer software (Cura, PrusaSlicer, etc.)

## 📦 Installation

1. Make sure you have Python 3.8+ installed

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## 🚀 Usage

Run the script to generate your hydrogen molecule:

```bash
python hydrogen_molecule.py
```

This creates `hydrogen_molecule.stl` in the current directory.

### Customizing Your Model

Edit the parameters in `hydrogen_molecule.py`:

```python
create_hydrogen_molecule(
    atom_radius=10.0,      # Size of each atom (mm)
    bond_radius=3.0,       # Thickness of the bond (mm)
    bond_length=25.0,      # Distance between atoms (mm)
    resolution=48,         # Mesh smoothness (24-64 recommended)
    output_file="hydrogen_molecule.stl"
)
```

**Parameter Guide:**
| Parameter | Description | Recommended Range |
|-----------|-------------|-------------------|
| `atom_radius` | Size of hydrogen spheres | 8-15 mm |
| `bond_radius` | Thickness of the connecting cylinder | 2-4 mm |
| `bond_length` | Distance between atom centers | 20-30 mm |
| `resolution` | Mesh detail level | 24 (draft) to 64 (smooth) |

## 🖨️ 3D Printing Tips

### Recommended Settings
- **Layer Height:** 0.1-0.2 mm
- **Infill:** 15-20%
- **Supports:** Usually not needed
- **Material:** PLA (easy to print, looks great)

### Model Size
With default settings, the model is approximately:
- Length: ~45 mm
- Height: ~20 mm
- Width: ~20 mm

Scale it up or down in your slicer as needed!

## 🖨️ Printing on a Bambu printer (skill)

This repo ships a Claude Code skill, **`print-to-bambu`**, that slices an STL and
prints it on a Bambu Lab printer over your local network — with a confirmation
gate before anything actually prints.

**First-time setup:** run the **`/onboard`** skill. It installs/locates a slicer
(Bambu Studio or OrcaSlicer), creates a Python venv, scaffolds a gitignored
`bambu.toml`, helps you find the printer IP / serial / access code, and walks you
through enabling **Developer / LAN Mode** (required to *start* prints).

Quick manual path once set up (run with the venv's Python):

```bash
python3 -m venv .venv
.venv/bin/pip install -r .claude/skills/print-to-bambu/requirements.txt
.venv/bin/python .claude/skills/print-to-bambu/scripts/setup_config.py   # edit bambu.toml
.venv/bin/python .claude/skills/print-to-bambu/scripts/preflight.py       # all ✓?
.venv/bin/python .claude/skills/print-to-bambu/scripts/view.py hydrogen_molecule.stl --open   # 3D preview
.venv/bin/python .claude/skills/print-to-bambu/scripts/slice.py hydrogen_molecule.stl         # -> .gcode.3mf + summary
# review the printed summary, then:
.venv/bin/python .claude/skills/print-to-bambu/scripts/send.py hydrogen_molecule.gcode.3mf    # add --dry-run to test
.venv/bin/python .claude/skills/print-to-bambu/scripts/monitor.py                              # live progress
```

Notes:
- **`bambu.toml` is gitignored** (it holds your LAN access code). Only
  `bambu.toml.example` is committed.
- Requires the printer in **Developer/LAN Mode** to start a print; slicing and
  monitoring work without it.
- The **3D viewer** (`view.py`) writes a self-contained HTML you can orbit/zoom in
  any browser.

## 🧩 Designing models from a description (skill)

The **`design-stl`** skill turns a description into a *printable* STL via an
OpenSCAD generate→verify loop: Claude writes OpenSCAD, `build.py` renders preview
images + an STL and runs printability checks (bed fit, watertight/manifold,
min wall thickness, overhangs), and Claude iterates until it's right — then hands
the STL to `print-to-bambu`.

```bash
brew install --cask openscad
.venv/bin/pip install -r .claude/skills/design-stl/requirements.txt   # trimesh, scipy, rtree
# Claude writes model.scad, then:
.venv/bin/python .claude/skills/design-stl/scripts/build.py model.scad   # STL + previews + report
.venv/bin/python .claude/skills/design-stl/scripts/validate.py any.stl    # checks on any STL
```

## 📁 Project Structure

```
3dprint/
├── hydrogen_molecule.py   # Main script to generate the model
├── requirements.txt       # Python dependencies
├── README.md             # This file
└── hydrogen_molecule.stl # Generated model (after running script)
```

## 🔬 About Hydrogen Molecules

Hydrogen (H₂) is the simplest and most abundant molecule in the universe! 

- **Atoms:** 2 hydrogen atoms
- **Bond Type:** Single covalent bond
- **Real Bond Length:** ~74 picometers (we scale it up for printing!)

This model is a great educational tool for:
- Learning about molecular structure
- Understanding covalent bonding
- Chemistry class demonstrations

## 📝 License

MIT License - Feel free to use, modify, and share!

---

Happy Printing! 🎉

