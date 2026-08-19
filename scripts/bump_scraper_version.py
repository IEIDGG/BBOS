import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def next_patch_version(version: str) -> str:
    parts = str(version).split(".")
    if not parts or not all(part.isdigit() for part in parts) or len(parts) > 4:
        raise ValueError(f"Invalid Chrome extension version: {version}")
    parts[-1] = str(int(parts[-1]) + 1)
    logger.info("Bumping scraper version from %s to %s", version, ".".join(parts))
    return ".".join(parts)


def should_bump_extension(
    changed_paths: list[str],
    manifest_path: str = "chrome_extension/manifest.json",
    old_manifest_text: Optional[str] = None,
    new_manifest_text: Optional[str] = None,
) -> bool:
    normalized = [path.replace("\\", "/") for path in changed_paths]
    normalized_manifest_path = manifest_path.replace("\\", "/")
    relevant = [path for path in normalized if path.startswith("chrome_extension/")]
    if not relevant:
        logger.info("Scraper version bump skipped: no chrome_extension changes")
        return False
    non_manifest = [path for path in relevant if path != normalized_manifest_path]
    if non_manifest:
        return True
    if old_manifest_text is not None and new_manifest_text is not None:
        try:
            old_manifest = json.loads(old_manifest_text)
            new_manifest = json.loads(new_manifest_text)
        except json.JSONDecodeError:
            logger.warning("Scraper version bump skipped: unable to parse manifest diff")
            return False
        old_manifest.pop("version", None)
        new_manifest.pop("version", None)
        if old_manifest != new_manifest:
            return True
    logger.info("Scraper version bump skipped: manifest-only change")
    return False


def bump_manifest_version(manifest_path: Path) -> tuple[str, str]:
    with manifest_path.open(encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)
    old_version = str(manifest.get("version", ""))
    new_version = next_patch_version(old_version)
    manifest["version"] = new_version
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    logger.info("Wrote scraper manifest version %s -> %s", old_version, new_version)
    return old_version, new_version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--changed-file", action="append", default=[])
    args = parser.parse_args(argv)
    normalized_files = [path.replace("\\", "/") for path in args.changed_file]
    old_manifest_text = None
    new_manifest_text = None
    if normalized_files == ["chrome_extension/manifest.json"]:
        try:
            old_manifest_text = subprocess.run(
                [
                    "git",
                    "show",
                    "HEAD~1:chrome_extension/manifest.json",
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            new_manifest_text = Path(args.manifest).read_text(encoding="utf-8")
        except (OSError, subprocess.CalledProcessError):
            old_manifest_text = None
            new_manifest_text = None
    if not should_bump_extension(
        args.changed_file,
        old_manifest_text=old_manifest_text,
        new_manifest_text=new_manifest_text,
    ):
        logger.info("No scraper version bump")
        return 0
    old_version, new_version = bump_manifest_version(Path(args.manifest))
    logger.info("Bumped %s -> %s", old_version, new_version)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(main())
