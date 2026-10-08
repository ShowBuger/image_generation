"""A local Chinese conversational agent for image generation and editing."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from datetime import datetime

try:
    from image_api import edit, generate, load_env
except ImportError:  # module import when used by a package runner
    from .image_api import edit, generate, load_env


HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
INDEX = OUT / "image_history.json"
SUPPORTED = {".png", ".jpg", ".jpeg", ".webp"}


def read_history() -> list[dict[str, str]]:
    try:
        rows = json.loads(INDEX.read_text(encoding="utf-8"))
        return [r for r in rows if isinstance(r, dict) and Path(r.get("path", "")).is_file()]
    except (OSError, json.JSONDecodeError, TypeError):
        return []


def write_history(rows: list[dict[str, str]]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(rows[-100:], ensure_ascii=False, indent=2), encoding="utf-8")


def add_history(path: Path, prompt: str, action: str) -> None:
    rows = read_history()
    rows.append({"path": str(path.resolve()), "prompt": prompt, "action": action,
                 "created": datetime.now().isoformat(timespec="seconds")})
    write_history(rows)


def list_images() -> list[Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    return sorted((p.resolve() for p in OUT.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def display_images() -> list[Path]:
    images = list_images()
    if not images:
        print("输出目录还没有图片。")
        return images
    for i, path in enumerate(images, 1):
        print(f"{i}. {path.name}  [{path}]")
    return images


def select_image(reference: str, images: list[Path]) -> Path | None:
    text = reference.strip().strip('"').strip("'")
    if re.search(r"上一张|刚才那张|最新一张|最后一张", text):
        return images[0] if images else None
    number = re.search(r"第\s*(\d+)\s*张", text)
    if number:
        idx = int(number.group(1))
        return images[idx - 1] if 1 <= idx <= len(images) else None
    candidate = Path(text).expanduser()
    if candidate.is_file() and candidate.suffix.lower() in SUPPORTED:
        return candidate.resolve()
    matches = [p for p in images if text and (text.lower() in p.name.lower() or p.stem.lower() == text.lower())]
    if len(matches) == 1:
        return matches[0]
    if len(images) == 1 and re.search(r"(这张|这幅|这个图|图片|图像)", text):
        return images[0]
    return None


def choose_pending(pending: dict, reply: str, images: list[Path]) -> list[Path] | None:
    if re.search(r"取消|算了|不改", reply):
        return []
    chosen = select_image(reply, images)
    if chosen:
        return [chosen]
    # Allow an explicit path containing spaces when the whole reply is the path.
    path = Path(reply.strip().strip('"')).expanduser()
    if path.is_file() and path.suffix.lower() in SUPPORTED:
        return [path.resolve()]
    return None


def conversational_intent(text: str) -> tuple[str, str]:
    stripped = text.strip()
    if stripped.startswith("/generate "):
        return "generate", stripped[len("/generate "):].strip()
    if stripped.startswith("/edit "):
        return "edit", stripped[len("/edit "):].strip()
    if re.fullmatch(r"/list|列表|图片列表|有哪些图片", stripped):
        return "list", ""
    if re.fullmatch(r"/help|帮助|怎么用", stripped):
        return "help", ""
    if re.fullmatch(r"/quit|退出|结束", stripped):
        return "quit", ""
    if re.search(r"编辑|修改|改一下|改成|替换|美化|去掉|添加到图|换背景|给.+加|把.+变成|让.+变", stripped):
        return "edit", stripped
    if re.search(r"生成|画一张|画个|创建图片|做一张|画图", stripped):
        return "generate", stripped
    return "unknown", stripped


def edit_request(text: str, images: list[Path]) -> tuple[str | None, list[Path] | None]:
    prompt = re.sub(r"^(?:请)?(?:编辑|修改|改一下|美化)\s*", "", text).strip()
    prompt = re.sub(r"^(?:上一张|刚才那张|最新一张|最后一张|第\s*\d+\s*张)\s*", "", prompt).strip(" ，,：:")
    prompt = re.sub(r"^(?:把)?(?:这张|这幅|这个图|图片|图像)\s*", "", prompt).strip(" ，,：:")

    # Full paths are accepted explicitly in quotes, or as a standalone path.
    quoted = re.findall(r"[\"']([^\"']+\.(?:png|jpe?g|webp))[\"']", text, flags=re.I)
    if quoted:
        path = Path(quoted[0]).expanduser()
        return prompt, ([path.resolve()] if path.is_file() else None)
    explicit_paths = re.findall(r"(?:[A-Za-z]:\\|\\\\)[^\"<>|?*\r\n]+?\.(?:png|jpe?g|webp)", text, flags=re.I)
    if explicit_paths:
        path = Path(explicit_paths[0].strip()).expanduser()
        return prompt, ([path.resolve()] if path.is_file() else None)

    matches = [p for p in images if p.name.lower() in text.lower() or p.stem.lower() in text.lower()]
    if len(matches) == 1:
        return prompt, matches
    if re.search(r"上一张|刚才那张|最新一张|最后一张", text) and images:
        return prompt, [images[0]]
    n = re.search(r"第\s*(\d+)\s*张", text)
    if n:
        idx = int(n.group(1))
        return prompt, ([images[idx - 1]] if 1 <= idx <= len(images) else None)
    if re.search(r"(这张|这幅|这个图|图片|图像)", text) and len(images) == 1:
        return prompt, [images[0]]
    if not images:
        return prompt, None
    return prompt, None


def help_text() -> None:
    print("我可以生成图片或编辑输出目录中的图片。示例：")
    print("  生成一张雨夜赛博朋克街景")
    print("  编辑上一张，把背景改成日落海边")
    print("  编辑第 2 张，移除桌上的杯子")
    print("  修改 computer.png，让机箱变成白色")
    print("  /list 查看图片；/quit 退出。也可以给出图片完整路径。")


def do_generate(prompt: str) -> None:
    if not prompt:
        print("请补充图片内容描述。")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    name = datetime.now().strftime("generated_%Y%m%d_%H%M%S.png")
    target = OUT / name
    path, status = generate(prompt, target)
    add_history(path, prompt, "generate")
    print(f"已生成并保存：{path}\nHTTP {status}")


def do_edit(prompt: str, targets: list[Path]) -> None:
    if not prompt:
        print("请说明要怎么编辑这张图片。")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    name = datetime.now().strftime("edited_%Y%m%d_%H%M%S.png")
    target = OUT / name
    path, status = edit(prompt, targets, target)
    add_history(path, prompt, "edit")
    print(f"已编辑并另存为：{path}\n原图保留不变。HTTP {status}")


def main() -> int:
    load_env()
    print("本地图片助手已启动。输入 /help 查看用法，/quit 退出。")
    pending: dict | None = None
    while True:
        try:
            text = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出图片助手。")
            return 0
        if not text:
            continue
        if pending:
            candidates = list_images()
            chosen = choose_pending(pending, text, candidates)
            if chosen == []:
                pending = None
                print("已取消编辑。")
            elif chosen:
                current = pending
                pending = None
                try:
                    do_edit(current["prompt"], chosen)
                except (OSError, RuntimeError) as exc:
                    print(f"编辑失败：{exc}")
            else:
                print("没有识别到唯一图片，请输入列表编号、文件名或完整路径；输入‘取消’放弃。")
                display_images()
            continue

        intent, content = conversational_intent(text)
        if intent == "quit":
            print("已退出图片助手。")
            return 0
        if intent == "help":
            help_text()
        elif intent == "list":
            display_images()
        elif intent == "generate":
            try:
                do_generate(content)
            except (OSError, RuntimeError) as exc:
                print(f"生成失败：{exc}")
        elif intent == "edit":
            images = list_images()
            prompt, targets = edit_request(content, images)
            if not targets:
                if not images:
                    print("输出目录里没有图片。请先生成一张，或提供要编辑图片的完整路径。")
                    continue
                print("你想编辑哪一张？请回复列表编号、文件名或图片完整路径。")
                pending = {"prompt": prompt or content}
                display_images()
                continue
            try:
                do_edit(prompt or content, targets)
            except (OSError, RuntimeError) as exc:
                print(f"编辑失败：{exc}")
        else:
            print("我没识别出要生成还是编辑。可以说‘生成……’或‘编辑上一张……’，也可以输入 /help。")


if __name__ == "__main__":
    raise SystemExit(main())
