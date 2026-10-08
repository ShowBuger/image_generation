"""Small curl-backed client for the configured OpenAI-compatible image API."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlparse


HERE = Path(__file__).resolve().parent


def load_env(path: Path = HERE / ".env") -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _curl(args: list[str], *, stdin: str | None = None, timeout: int = 240) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["curl.exe", *args], input=stdin, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("找不到 curl.exe，请确认 Windows curl 已安装并加入 PATH。") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"图片接口请求超过 {timeout} 秒超时。") from exc


def _config() -> tuple[str, str]:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError(f"请先在 {HERE / '.env'} 中填写 OPENAI_API_KEY。")
    base = os.environ.get("IMAGE_API_BASE_URL", "https://dm-fox.rjj.cc/codex").rstrip("/")
    path = os.environ.get("IMAGE_API_PATH", "/v1/images/generations")
    return key, base + "/" + path.lstrip("/")


def _save_item(item: dict, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if item.get("b64_json"):
        target.write_bytes(base64.b64decode(item["b64_json"]))
    else:
        image_url = item.get("url", "")
        if urlparse(image_url).scheme != "https":
            raise RuntimeError("响应没有图片数据或有效的 HTTPS 图片 URL。")
        result = _curl(["--location", "--silent", "--show-error", "--fail", "--output", str(target), image_url])
        if result.returncode:
            target.unlink(missing_ok=True)
            raise RuntimeError(f"下载生成图片失败：{result.stderr.strip()}")
    content = target.read_bytes()
    if not (content.startswith(b"\x89PNG\r\n\x1a\n") or content.startswith(b"\xff\xd8\xff")):
        target.unlink(missing_ok=True)
        raise RuntimeError("接口返回内容不是有效的 PNG 或 JPEG 图片。")
    return target


def _request(url: str, fields: list[str], target: Path) -> tuple[Path, str]:
    key, _ = _config()
    with tempfile.TemporaryDirectory(prefix="image_api_") as temp:
        response_path = Path(temp) / "response.json"
        auth = f'header = "Authorization: Bearer {key}"\n'
        result = _curl([
            "--config", "-", "--location", "--silent", "--show-error",
            *fields, "--output", str(response_path), "--write-out", "%{http_code}", url,
        ], stdin=auth)
        if result.returncode:
            raise RuntimeError(f"请求传输失败：{result.stderr.strip()}")
        status = result.stdout.strip()
        raw = response_path.read_bytes() if response_path.exists() else b""
        if not status.startswith("2"):
            detail = raw.decode("utf-8", errors="replace")[:2000]
            raise RuntimeError(f"中转站返回 HTTP {status}: {detail}")
        try:
            body = json.loads(raw.decode("utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"HTTP {status} 响应不是有效 JSON：{raw[:400]!r}") from exc
    items = body.get("data") or []
    if not items:
        raise RuntimeError("成功响应中没有 data 图片结果。")
    return _save_item(items[0], target), status


def generate(prompt: str, target: Path) -> tuple[Path, str]:
    key, endpoint = _config()
    del key
    model = os.environ.get("IMAGE_MODEL", "gpt-image-2")
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "size": os.environ.get("IMAGE_SIZE", "1536x1024"),
        "quality": os.environ.get("IMAGE_QUALITY", "high"),
        "n": 1,
    }, ensure_ascii=False)
    with tempfile.TemporaryDirectory(prefix="image_payload_") as temp:
        path = Path(temp) / "request.json"
        path.write_text(payload, encoding="utf-8")
        return _request(endpoint, ["--request", "POST", "--header", "Content-Type: application/json", "--data-binary", f"@{path}"], target)


def edit(prompt: str, image_paths: list[Path], target: Path) -> tuple[Path, str]:
    if not image_paths:
        raise RuntimeError("请指定至少一张要编辑的图片。")
    for image in image_paths:
        if not image.is_file():
            raise RuntimeError(f"找不到图片文件：{image}")
    key, base_endpoint = _config()
    del key
    edit_path = os.environ.get("IMAGE_EDIT_API_PATH", "/v1/images/edits")
    edit_base = os.environ.get("IMAGE_API_BASE_URL", "https://dm-fox.rjj.cc/codex").rstrip("/")
    endpoint = edit_base + "/" + edit_path.lstrip("/")
    model = os.environ.get("IMAGE_MODEL", "gpt-image-2")
    fields = [
        "--request", "POST",
        "--form-string", f"model={model}",
        "--form-string", f"prompt={prompt}",
        "--form-string", f"size={os.environ.get('IMAGE_SIZE', '1536x1024')}",
        "--form-string", f"quality={os.environ.get('IMAGE_QUALITY', 'high')}",
        "--form-string", "response_format=b64_json",
    ]
    for image in image_paths:
        fields.extend(["--form", f"image=@{image.resolve()}"])
    return _request(endpoint, fields, target)
