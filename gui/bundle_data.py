"""Mac / Windows 共用的发布资源清单，不打包本地日志、备份或测试机型。"""
from pathlib import Path
import platform
import shutil
import sys

try:
    from . import hdc_fetch
except ImportError:
    import hdc_fetch


def bundle_data(root, platform_name=None, machine=None):
    root = Path(root).resolve()
    patterns = ("tool/**/*.py", "tool/*.dex", "recipe_lib/*.py", "recipes/*/*/*.toml",
                "recipes/*/*/*.py", "recipes/verified.toml", "images/*.png",
                "gui/web/index.html", "gui/web/chime.wav", "gui/web/img/*.png",
                "harmony/recipes.json", "harmony/desktop/vendor/NOTICE-hdc.txt")
    system = platform_name or sys.platform
    arch = machine or platform.machine()
    vendor = hdc_fetch.arch_of(system, arch)
    if vendor:
        patterns += (f"harmony/desktop/vendor/{vendor}/*",)
    data = []
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            rel = path.relative_to(root)
            if any(part.startswith("zztest-") for part in rel.parts):
                continue
            if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents) if p != root):
                continue
            data.append((str(path), rel.parent.as_posix()))
    return data


def stage(root, destination, machine=None):
    destination = Path(destination)
    for source, directory in bundle_data(root, machine=machine):
        target = destination / directory / Path(source).name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


if __name__ == "__main__":
    stage(Path(__file__).resolve().parents[1], sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
