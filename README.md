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

