import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bump_scraper_version.py"


def load_bump_script():
    spec = importlib.util.spec_from_file_location("bump_scraper_version", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NextPatchVersionTests(unittest.TestCase):
    def test_bumps_patch(self):
        module = load_bump_script()
        self.assertEqual(module.next_patch_version("1.1.7"), "1.1.8")

    def test_rejects_component_over_chrome_max(self):
        module = load_bump_script()
        with self.assertRaises(ValueError):
            module.next_patch_version(f"1.1.{module.CHROME_VERSION_COMPONENT_MAX}")


class ShouldBumpExtensionTests(unittest.TestCase):
    def test_skips_manifest_only(self):
        module = load_bump_script()
        self.assertFalse(
            module.should_bump_extension(["chrome_extension/manifest.json"])
        )

    def test_bumps_on_code_change(self):
        module = load_bump_script()
        self.assertTrue(module.should_bump_extension(["chrome_extension/popup.js"]))


class BumpManifestFileTests(unittest.TestCase):
    def test_writes_next_patch(self):
        module = load_bump_script()
        with tempfile.TemporaryDirectory() as temp:
            manifest = Path(temp) / "manifest.json"
            manifest.write_text(
                json.dumps({"name": "IEID Order Scraper", "version": "1.1.7"}),
                encoding="utf-8",
            )
            old_version, new_version = module.bump_manifest_version(manifest)
            self.assertEqual(old_version, "1.1.7")
            self.assertEqual(new_version, "1.1.8")
            self.assertEqual(json.loads(manifest.read_text())["version"], "1.1.8")


if __name__ == "__main__":
    unittest.main()
