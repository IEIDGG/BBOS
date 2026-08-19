import argparse
import json
import logging
import sys
from pathlib import Path

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
) -> bool:
    normalized = [path.replace("\\", "/") for path in changed_paths]
    relevant = [path for path in normalized if path.startswith("chrome_extension/")]
    if not relevant:
        logger.info("Scraper version bump skipped: no chrome_extension changes")
        return False
    non_manifest = [path for path in relevant if path != manifest_path]
    if not non_manifest:
        logger.info("Scraper version bump skipped: manifest-only change")
        return False
    return True


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
    if not should_bump_extension(args.changed_file):
        logger.info("No scraper version bump")
        return 0
    old_version, new_version = bump_manifest_version(Path(args.manifest))
    logger.info("Bumped %s -> %s", old_version, new_version)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(main())
