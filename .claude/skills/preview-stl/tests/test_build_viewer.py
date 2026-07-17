import base64
import gzip
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import trimesh


SCRIPT = Path(__file__).parents[1] / "scripts" / "build_viewer.py"
SPEC = importlib.util.spec_from_file_location("build_viewer", SCRIPT)
build_viewer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(build_viewer)


def unpack_part(part: dict) -> trimesh.Trimesh:
    raw = gzip.decompress(base64.b64decode(part["stl"]))
    return trimesh.load(io.BytesIO(raw), file_type="stl")


class BuildDemoScenesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.paths = [root / "left.stl", root / "right.stl"]
        for x, path in zip((-8.0, 8.0), self.paths):
            mesh = trimesh.creation.box(extents=[10.0, 10.0, 10.0])
            mesh.apply_translation([x, 0.0, 5.0])
            mesh.export(path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_demo_builds_assembly_and_moves_parts_outward(self) -> None:
        args = SimpleNamespace(
            inputs=[str(path) for path in self.paths],
            demo=True,
            title="Two boxes",
        )

        title, subtitle, scenes = build_viewer.build_scenes(args)

        self.assertEqual(title, "Two boxes")
        self.assertIn("Auto-generated", subtitle)
        self.assertEqual([scene["title"] for scene in scenes], ["Assembly", "Exploded"])
        self.assertEqual(
            [part["name"] for part in scenes[0]["parts"]],
            ["left", "right"],
        )

        assembled = [unpack_part(part).bounding_box.centroid
                     for part in scenes[0]["parts"]]
        exploded = [unpack_part(part).bounding_box.centroid
                    for part in scenes[1]["parts"]]
        for before, after in zip(assembled, exploded):
            self.assertGreater(np.linalg.norm(after), np.linalg.norm(before))

    def test_legacy_loose_file_mode_still_builds_one_scene_per_file(self) -> None:
        args = SimpleNamespace(
            inputs=[str(path) for path in self.paths],
            demo=False,
            title="Legacy",
        )

        title, subtitle, scenes = build_viewer.build_scenes(args)

        self.assertEqual(title, "Legacy")
        self.assertEqual(subtitle, "")
        self.assertEqual([scene["title"] for scene in scenes], ["left", "right"])

    def test_demo_rejects_manifest_input(self) -> None:
        args = SimpleNamespace(inputs=["presentation.json"], demo=True, title="Invalid")

        with self.assertRaisesRegex(ValueError, "accepts STL inputs"):
            build_viewer.build_scenes(args)


if __name__ == "__main__":
    unittest.main()
