"""Import explicitly selected local anchors; never attest aesthetic/model tests."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moss.aesthetics import AestheticProfile  # noqa: E402
from moss.references import normalize_image  # noqa: E402
from moss.storage import atomic_write  # noqa: E402


def main():
    """Create one new private profile from an explicit spec without overwriting.

    The spec follows AestheticProfile, but each anchor uses source_path/reason.
    Source paths are deliberately selected maintainer files, never QQ input.
    Verification flags are reset so importing cannot claim real acceptance.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    destination = args.destination.absolute()
    if destination.exists() or any(
        path.is_symlink() or path.is_junction()
        for path in (destination, *destination.parents)
    ):
        parser.error("Destination must be a new directory without linked parents")
    if args.spec.stat().st_size > 65536:
        parser.error("Spec exceeds size limit")
    data = json.loads(args.spec.read_text(encoding="utf-8"))
    images = {}
    for name, category in data["categories"].items():
        for kind in ("positive", "negative"):
            for index, anchor in enumerate(category[kind]):
                source = Path(anchor["source_path"])
                if not source.is_absolute() or source.stat().st_size > 8 * 1024 * 1024:
                    parser.error(
                        "Select explicit absolute image paths within the byte budget"
                    )
                normalized = normalize_image(source.read_bytes(), 1024)[0]
                if normalized in images.values():
                    parser.error(
                        "Choose distinct anchor artworks, never the same work as positive and negative"
                    )
                filename = f"{name}-{kind}-{index}.jpg"
                category[kind][index] = {
                    "file": filename,
                    "sha256": hashlib.sha256(normalized).hexdigest(),
                    "reason": anchor["reason"],
                }
                images[filename] = normalized
        category["calibrated"] = False
    data["multimodal_verified"] = False
    data["sources_verified"] = False
    profile = AestheticProfile.model_validate(data)
    if len(images) > 16 or sum(map(len, images.values())) > 16 * 1024 * 1024:
        parser.error("Anchor budget exceeded")
    destination.mkdir(parents=True, mode=0o700)
    for name, content in images.items():
        target = destination / name
        with target.open("xb") as handle:
            target.chmod(0o600)
            handle.write(content)
    atomic_write(destination / "manifest.json", profile.model_dump())
    print(
        "Profile imported with verification disabled; complete explicit calibration before enabling draw."
    )


if __name__ == "__main__":
    main()
