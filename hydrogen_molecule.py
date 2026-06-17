"""
Hydrogen Molecule (H2) 3D Model Generator for 3D Printing

This script creates a 3D printable STL file of a hydrogen molecule,
consisting of two hydrogen atoms (spheres) connected by a bond (cylinder).
"""

import numpy as np
from stl import mesh
import math


def create_sphere(radius: float, center: tuple, resolution: int = 32) -> mesh.Mesh:
    """
    Create a sphere mesh at the specified center point.
    
    Args:
        radius: Radius of the sphere
        center: (x, y, z) coordinates of the sphere center
        resolution: Number of segments for sphere detail (higher = smoother)
    
    Returns:
        A mesh object representing the sphere
    """
    cx, cy, cz = center
    
    # Generate sphere vertices using spherical coordinates
    phi = np.linspace(0, np.pi, resolution)  # latitude
    theta = np.linspace(0, 2 * np.pi, resolution)  # longitude
    
    # Create meshgrid for spherical coordinates
    phi, theta = np.meshgrid(phi, theta)
    
    # Convert to Cartesian coordinates
    x = radius * np.sin(phi) * np.cos(theta) + cx
    y = radius * np.sin(phi) * np.sin(theta) + cy
    z = radius * np.cos(phi) + cz
    
    # Create triangles from the grid
    triangles = []
    for i in range(resolution - 1):
        for j in range(resolution - 1):
            # First triangle of quad
            p1 = [x[i, j], y[i, j], z[i, j]]
            p2 = [x[i + 1, j], y[i + 1, j], z[i + 1, j]]
            p3 = [x[i, j + 1], y[i, j + 1], z[i, j + 1]]
            triangles.append([p1, p2, p3])
            
            # Second triangle of quad
            p1 = [x[i + 1, j], y[i + 1, j], z[i + 1, j]]
            p2 = [x[i + 1, j + 1], y[i + 1, j + 1], z[i + 1, j + 1]]
            p3 = [x[i, j + 1], y[i, j + 1], z[i, j + 1]]
            triangles.append([p1, p2, p3])
    
    # Create mesh
    sphere = mesh.Mesh(np.zeros(len(triangles), dtype=mesh.Mesh.dtype))
    for i, tri in enumerate(triangles):
        sphere.vectors[i] = np.array(tri)
    
    return sphere


def create_cylinder(radius: float, start: tuple, end: tuple, resolution: int = 32) -> mesh.Mesh:
    """
    Create a cylinder mesh between two points.
    
    Args:
        radius: Radius of the cylinder
        start: (x, y, z) start point
        end: (x, y, z) end point
        resolution: Number of segments around the cylinder
    
    Returns:
        A mesh object representing the cylinder
    """
    start = np.array(start)
    end = np.array(end)
    
    # Calculate cylinder axis
    axis = end - start
    length = np.linalg.norm(axis)
    axis_normalized = axis / length
    
    # Find perpendicular vectors for the circular cross-section
    if abs(axis_normalized[0]) < 0.9:
        perp1 = np.cross(axis_normalized, [1, 0, 0])
    else:
        perp1 = np.cross(axis_normalized, [0, 1, 0])
    perp1 = perp1 / np.linalg.norm(perp1)
    perp2 = np.cross(axis_normalized, perp1)
    
    # Generate circle points
    angles = np.linspace(0, 2 * np.pi, resolution, endpoint=False)
    
    # Create triangles for cylinder body
    triangles = []
    
    for i in range(resolution):
        angle1 = angles[i]
        angle2 = angles[(i + 1) % resolution]
        
        # Points on bottom circle
        b1 = start + radius * (np.cos(angle1) * perp1 + np.sin(angle1) * perp2)
        b2 = start + radius * (np.cos(angle2) * perp1 + np.sin(angle2) * perp2)
        
        # Points on top circle
        t1 = end + radius * (np.cos(angle1) * perp1 + np.sin(angle1) * perp2)
        t2 = end + radius * (np.cos(angle2) * perp1 + np.sin(angle2) * perp2)
        
        # Two triangles for each quad on the cylinder side
        triangles.append([b1.tolist(), b2.tolist(), t1.tolist()])
        triangles.append([b2.tolist(), t2.tolist(), t1.tolist()])
    
    # Create end caps
    for i in range(resolution):
        angle1 = angles[i]
        angle2 = angles[(i + 1) % resolution]
        
        # Bottom cap
        b1 = start + radius * (np.cos(angle1) * perp1 + np.sin(angle1) * perp2)
        b2 = start + radius * (np.cos(angle2) * perp1 + np.sin(angle2) * perp2)
        triangles.append([start.tolist(), b2.tolist(), b1.tolist()])
        
        # Top cap
        t1 = end + radius * (np.cos(angle1) * perp1 + np.sin(angle1) * perp2)
        t2 = end + radius * (np.cos(angle2) * perp1 + np.sin(angle2) * perp2)
        triangles.append([end.tolist(), t1.tolist(), t2.tolist()])
    
    # Create mesh
    cylinder = mesh.Mesh(np.zeros(len(triangles), dtype=mesh.Mesh.dtype))
    for i, tri in enumerate(triangles):
        cylinder.vectors[i] = np.array(tri)
    
    return cylinder


def combine_meshes(meshes: list) -> mesh.Mesh:
    """Combine multiple meshes into a single mesh."""
    total_faces = sum(len(m.vectors) for m in meshes)
    combined = mesh.Mesh(np.zeros(total_faces, dtype=mesh.Mesh.dtype))
    
    offset = 0
    for m in meshes:
        for i, vector in enumerate(m.vectors):
            combined.vectors[offset + i] = vector
        offset += len(m.vectors)
    
    return combined


def create_hydrogen_molecule(
    atom_radius: float = 10.0,
    bond_radius: float = 3.0,
    bond_length: float = 25.0,
    resolution: int = 48,
    output_file: str = "hydrogen_molecule.stl"
) -> str:
    """
    Create a 3D printable hydrogen molecule model.
    
    Args:
        atom_radius: Radius of each hydrogen atom sphere (mm)
        bond_radius: Radius of the bond cylinder (mm)
        bond_length: Distance between atom centers (mm)
        resolution: Mesh resolution (higher = smoother, larger file)
        output_file: Name of the output STL file
    
    Returns:
        Path to the created STL file
    """
    print("🔬 Creating Hydrogen Molecule (H₂) Model...")
    print(f"   Atom radius: {atom_radius} mm")
    print(f"   Bond radius: {bond_radius} mm")
    print(f"   Bond length: {bond_length} mm")
    print(f"   Resolution: {resolution}")
    
    # Calculate atom positions (centered at origin)
    half_bond = bond_length / 2
    atom1_center = (-half_bond, 0, 0)
    atom2_center = (half_bond, 0, 0)
    
    # Create the two hydrogen atoms
    print("\n⚛️  Creating hydrogen atom 1...")
    atom1 = create_sphere(atom_radius, atom1_center, resolution)
    
    print("⚛️  Creating hydrogen atom 2...")
    atom2 = create_sphere(atom_radius, atom2_center, resolution)
    
    # Create the bond between atoms
    # The bond cylinder connects the surfaces of the atoms, not their centers
    bond_start = (-half_bond + atom_radius * 0.3, 0, 0)
    bond_end = (half_bond - atom_radius * 0.3, 0, 0)
    
    print("🔗 Creating molecular bond...")
    bond = create_cylinder(bond_radius, bond_start, bond_end, resolution)
    
    # Combine all parts
    print("\n🔧 Combining mesh components...")
    molecule = combine_meshes([atom1, atom2, bond])
    
    # Save to STL file
    molecule.save(output_file)
    
    # Get file info
    num_triangles = len(molecule.vectors)
    
    print(f"\n✅ Success! Model saved to: {output_file}")
    print(f"   Total triangles: {num_triangles:,}")
    print(f"\n📋 Printing Tips:")
    print("   • Recommended layer height: 0.1-0.2 mm")
    print("   • Infill: 15-20% for a good balance")
    print("   • Supports: Usually not needed (flat base)")
    print("   • Material: PLA works great for display models")
    
    return output_file


if __name__ == "__main__":
    # Create the hydrogen molecule with default parameters
    # You can adjust these values to change the model size
    create_hydrogen_molecule(
        atom_radius=10.0,      # Hydrogen atom size in mm
        bond_radius=3.0,       # Bond thickness in mm
        bond_length=25.0,      # Distance between atoms in mm
        resolution=48,         # Higher = smoother surface
        output_file="hydrogen_molecule.stl"
    )

