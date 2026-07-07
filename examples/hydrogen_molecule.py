"""
Hydrogen Molecule (H2) 3D Model Generator for 3D Printing

Two hydrogen atoms (spheres) connected by a bond (cylinder), with the sphere
bottoms cut flat so the model stands on two solid discs instead of touching
the plate in two points. Point contact slices fine but detaches mid-print —
even a brim only holds a ~2 mm neck (learned the hard way on a real print).

Requires trimesh + manifold3d (see examples/requirements.txt).
"""

import math

import trimesh


def create_hydrogen_molecule(
    atom_radius: float = 10.0,
    bond_radius: float = 3.0,
    bond_length: float = 25.0,
    base_cut: float = 2.0,
    output_file: str = "hydrogen_molecule.stl",
) -> str:
    """
    Create a 3D printable hydrogen molecule model.

    Args:
        atom_radius: Radius of each hydrogen atom sphere (mm)
        bond_radius: Radius of the bond cylinder (mm)
        bond_length: Distance between atom centers (mm)
        base_cut: How much to shave off the sphere bottoms for the flat base
            (mm). 2.0 on a 10 mm sphere gives two 12 mm-diameter contact discs.
        output_file: Name of the output STL file

    Returns:
        Path to the created STL file
    """
    print("🔬 Creating Hydrogen Molecule (H₂) Model...")
    print(f"   Atom radius: {atom_radius} mm")
    print(f"   Bond radius: {bond_radius} mm")
    print(f"   Bond length: {bond_length} mm")
    print(f"   Base cut: {base_cut} mm")

    half = bond_length / 2

    atom1 = trimesh.creation.icosphere(subdivisions=4, radius=atom_radius)
    atom1.apply_translation([-half, 0, 0])
    atom2 = trimesh.creation.icosphere(subdivisions=4, radius=atom_radius)
    atom2.apply_translation([half, 0, 0])

    bond = trimesh.creation.cylinder(radius=bond_radius, height=bond_length,
                                     sections=64)
    bond.apply_transform(
        trimesh.transformations.rotation_matrix(math.pi / 2, [0, 1, 0]))

    print("🔧 Combining and flattening the base...")
    molecule = trimesh.boolean.union([atom1, atom2, bond])

    # Cut everything below the base plane and cap it, so each atom stands on a
    # flat disc of radius sqrt(r^2 - (r - base_cut)^2).
    cut_z = -atom_radius + base_cut
    keep = trimesh.creation.box(bounds=[[-2 * bond_length, -2 * atom_radius, cut_z],
                                        [2 * bond_length, 2 * atom_radius,
                                         2 * atom_radius]])
    molecule = trimesh.boolean.intersection([molecule, keep])
    molecule.apply_translation([0, 0, -cut_z])  # flat base at z=0

    assert molecule.is_watertight, "boolean result is not watertight"
    molecule.export(output_file)

    disc_r = math.sqrt(atom_radius ** 2 - (atom_radius - base_cut) ** 2)
    print(f"\n✅ Success! Model saved to: {output_file}")
    print(f"   Triangles: {len(molecule.faces):,}")
    print(f"   Size: {[round(float(v), 1) for v in molecule.extents]} mm")
    print(f"   Base: two flat discs of Ø{2 * disc_r:.1f} mm")
    print("\n📋 Printing Tips:")
    print("   • Layer height 0.1–0.2 mm, 15–20% infill, PLA")
    print("   • No supports needed: flat base + short bond bridge")

    return output_file


if __name__ == "__main__":
    create_hydrogen_molecule(
        atom_radius=10.0,      # Hydrogen atom size in mm
        bond_radius=3.0,       # Bond thickness in mm
        bond_length=25.0,      # Distance between atom centers in mm
        base_cut=2.0,          # Flat-base depth in mm
        output_file="hydrogen_molecule.stl",
    )
