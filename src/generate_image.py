"""Generate or edit images using the configured FoxCode compatible API."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

try:
    from image_api import edit, generate, load_env
except ImportError:  # module import when used by a package runner
    from .image_api import edit, generate, load_env


HERE = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", help="Generation or edit instruction")
    parser.add_argument("-o", "--output", type=Path, default=HERE / "output" / "generated.png")
    parser.add_argument("--edit", nargs="+", type=Path, metavar="IMAGE", help="Edit these input image(s)")
    parser.add_argument("--env-file", type=Path, default=HERE / ".env")
    args = parser.parse_args()
    load_env(args.env_file)
    try:
        path, status = edit(args.prompt, args.edit, args.output) if args.edit else generate(args.prompt, args.output)
        print(f"图片已保存：{path.resolve()}（HTTP {status}，模型 {os.environ.get('IMAGE_MODEL', 'gpt-image-2')}）")
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"生图失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
