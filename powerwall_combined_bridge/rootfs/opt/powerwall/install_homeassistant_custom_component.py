#!/usr/bin/env python3

from __future__ import annotations

import argparse
import filecmp
import shutil
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install or update the Powerwall Combined Bridge custom component into Home Assistant config.",
    )
    parser.add_argument(
        "--source",
        default="/opt/powerwall/homeassistant_custom_component/powerwall_combined_bridge",
        help="Source directory containing the vendored custom component",
    )
    parser.add_argument(
        "--target",
        default="/homeassistant_config/custom_components/powerwall_combined_bridge",
        help="Target custom component directory under Home Assistant config",
    )
    return parser.parse_args()


def directories_match(source: Path, target: Path) -> bool:
    if not source.is_dir() or not target.is_dir():
        return False

    comparison = filecmp.dircmp(source, target)
    if comparison.left_only or comparison.right_only or comparison.funny_files:
        return False
    if comparison.diff_files:
        return False

    return all(directories_match(source / name, target / name) for name in comparison.common_dirs)


def install_component(source: Path, target: Path) -> bool:
    if not source.is_dir():
        raise FileNotFoundError(f"Source component directory not found: {source}")

    target.parent.mkdir(parents=True, exist_ok=True)
    if directories_match(source, target):
        return False

    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    return True


def main() -> int:
    args = parse_args()
    source = Path(args.source)
    target = Path(args.target)
    changed = install_component(source, target)
    if changed:
        print(f"Installed custom component to {target}")
    else:
        print(f"Custom component already up to date at {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())