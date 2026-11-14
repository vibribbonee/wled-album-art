"""Copy the root documentation into the distributable integration folder."""
from pathlib import Path
from shutil import copyfile


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    component = root / "custom_components" / "wled_album_art"
    for name in ("README.md", "CHANGELOG.md"):
        copyfile(root / name, component / name)
        print(f"Updated custom_components/wled_album_art/{name}")


if __name__ == "__main__":
    main()
