#!/usr/bin/env python3

from __future__ import annotations

import argparse
import filecmp
import shutil
from pathlib import Path


DEFAULT_SOURCE = "/opt/powerwall/homeassistant_custom_component/powerwall_combined_bridge"
DEFAULT_TARGET = "/homeassistant_config/custom_components/powerwall_combined_bridge"
CONFIG_ROOT_CANDIDATES = (
    Path("/homeassistant"),
    Path("/homeassistant_config"),
    Path("/config"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install or update the Powerwall Combined Bridge custom component into Home Assistant config.",
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_SOURCE,
        help="Source directory containing the vendored custom component",
    )
    parser.add_argument(
        "--target",
        default=DEFAULT_TARGET,
        help="Target custom component directory under Home Assistant config",
    )
    return parser.parse_args()


def looks_like_homeassistant_config_root(path: Path) -> bool:
    return (path / "configuration.yaml").exists() or (path / ".storage").exists()


def resolve_target(target: Path) -> Path:
    if str(target) != DEFAULT_TARGET:
        return target

    for root in CONFIG_ROOT_CANDIDATES:
        if looks_like_homeassistant_config_root(root):
            return root / "custom_components" / "powerwall_combined_bridge"

    return target


def describe_target_resolution(target: Path) -> str:
    if str(target) != DEFAULT_TARGET:
        return f"Using explicit target {target}"

    resolved = resolve_target(target)
    if resolved == target:
        candidates = ", ".join(str(path) for path in CONFIG_ROOT_CANDIDATES)
        return f"No Home Assistant config markers found under: {candidates}. Falling back to {target}"

    return f"Detected Home Assistant config root at {resolved.parent.parent}; installing to {resolved}"


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
    requested_target = Path(args.target)
    print(describe_target_resolution(requested_target))
    target = resolve_target(requested_target)
    changed = install_component(source, target)
    if changed:
        print(f"Installed custom component to {target}")
    else:
        print(f"Custom component already up to date at {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())