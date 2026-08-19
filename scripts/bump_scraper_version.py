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
            logger.warning(
                "Scraper version bump skipped: unable to parse manifest diff"
            )
            return False
        old_without_version = dict(old_manifest)
        new_without_version = dict(new_manifest)
        old_without_version.pop("version", None)
        new_without_version.pop("version", None)
        if old_without_version != new_without_version:
            return True
    if not non_manifest:
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


def load_manifest_texts(
    manifest_path: Path, changed_files: list[str], base_ref: str
) -> tuple[Optional[str], Optional[str]]:
    normalized_files = [path.replace("\\", "/") for path in changed_files]
    relevant = [
        path for path in normalized_files if path.startswith("chrome_extension/")
    ]
    non_manifest = [
        path for path in relevant if path != "chrome_extension/manifest.json"
    ]
    if "chrome_extension/manifest.json" not in relevant or non_manifest:
        return None, None
    try:
        old_manifest_text = subprocess.run(
            ["git", "show", f"{base_ref}:chrome_extension/manifest.json"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        new_manifest_text = manifest_path.read_text(encoding="utf-8")
        return old_manifest_text, new_manifest_text
    except (OSError, subprocess.CalledProcessError):
        logger.warning("Unable to load previous scraper manifest from %s", base_ref)
        return None, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--base-ref", default="HEAD~1")
    args = parser.parse_args(argv)
    old_manifest_text, new_manifest_text = load_manifest_texts(
        Path(args.manifest), args.changed_file, args.base_ref
    )
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
