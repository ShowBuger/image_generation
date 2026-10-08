"""Local-only web UI server for the image generation/editing agent."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
import re
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse
import webbrowser

from image_api import edit, generate, load_env


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
OUT = ROOT / "output"
ENV_FILE = ROOT / ".env"
MAX_JSON_BYTES = 40 * 1024 * 1024
LOCK = threading.Lock()
MIME_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}


def read_local_config() -> dict[str, str]:
    values: dict[str, str] = {}
    if ENV_FILE.exists():
        for raw in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def save_local_config(updates: dict) -> dict[str, str]:
    allowed = {
        "IMAGE_API_BASE_URL", "IMAGE_API_PATH", "IMAGE_EDIT_API_PATH",
        "IMAGE_MODEL", "IMAGE_SIZE", "IMAGE_QUALITY", "IMAGE_COUNT",
    }
    old = read_local_config()
    for key in allowed:
        if key in updates:
            value = str(updates[key]).strip()
            if "\n" in value or "\r" in value:
                raise ValueError(f"配置项 {key} 不能包含换行符。")
            old[key] = value
    if "api_key" in updates and str(updates["api_key"]).strip():
        key = str(updates["api_key"]).strip()
        if "\n" in key or "\r" in key:
            raise ValueError("API Key 不能包含换行符。")
        old["OPENAI_API_KEY"] = key

    ordered = ["OPENAI_API_KEY", "IMAGE_API_BASE_URL", "IMAGE_API_PATH", "IMAGE_EDIT_API_PATH", "IMAGE_MODEL", "IMAGE_SIZE", "IMAGE_QUALITY", "IMAGE_COUNT"]
    content = "\n".join(f"{key}={old[key]}" for key in ordered if key in old) + "\n"
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = ENV_FILE.with_suffix(".env.tmp")
    temp.write_text(content, encoding="utf-8")
    temp.replace(ENV_FILE)
    # Ensure new settings take effect immediately in this server process.
    os.environ.update(old)
    return old


def load_history() -> list[dict]:
    history_file = OUT / "image_history.json"
    try:
        rows = json.loads(history_file.read_text(encoding="utf-8"))
        return [row for row in rows if isinstance(row, dict)]
    except (OSError, json.JSONDecodeError):
        return []


def record_image(path: Path, prompt: str, action: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    history = load_history()
    history.append({"path": str(path.resolve()), "prompt": prompt, "action": action,
                    "created": datetime.now().isoformat(timespec="seconds")})
    (OUT / "image_history.json").write_text(json.dumps(history[-100:], ensure_ascii=False, indent=2), encoding="utf-8")


def unique_target(prefix: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return OUT / f"{prefix}_{stamp}.png"


class Handler(BaseHTTPRequestHandler):
    server_version = "LocalImageStudio/1.0"

    def log_message(self, fmt: str, *args) -> None:
        # Avoid logging query strings or any request payloads.
        print(f"[image-ui] {self.address_string()} {fmt % args}")

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > MAX_JSON_BYTES:
            raise ValueError("请求体为空或超过 40 MB 限制。")
        data = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("请求 JSON 必须是对象。")
        return data

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/config":
            cfg = read_local_config()
            self._json(200, {
                "base_url": cfg.get("IMAGE_API_BASE_URL", "https://dm-fox.rjj.cc/codex"),
                "generation_path": cfg.get("IMAGE_API_PATH", "/v1/images/generations"),
                "edit_path": cfg.get("IMAGE_EDIT_API_PATH", "/v1/images/edits"),
                "model": cfg.get("IMAGE_MODEL", "gpt-image-2.5"),
                "size": cfg.get("IMAGE_SIZE", "1536x1024"),
                "quality": cfg.get("IMAGE_QUALITY", "high"),
                "count": cfg.get("IMAGE_COUNT", "1"),
                "api_key_set": bool(cfg.get("OPENAI_API_KEY", "").strip()),
            })
            return
        if parsed.path == "/api/images":
            OUT.mkdir(parents=True, exist_ok=True)
            images = []
            for path in sorted(OUT.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                    images.append({"name": path.name, "url": f"/output/{path.name}", "bytes": path.stat().st_size})
            self._json(200, {"images": images[:100]})
            return
        if parsed.path.startswith("/output/"):
            name = unquote(parsed.path.removeprefix("/output/"))
            if Path(name).name != name:
                self.send_error(400, "Invalid output file name")
                return
            path = (OUT / name).resolve()
            if path.parent != OUT.resolve() or not path.is_file():
                self.send_error(404)
                return
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
            return
        asset = "index.html" if parsed.path in {"/", "/index.html"} else parsed.path.lstrip("/")
        if asset not in {"index.html"}:
            self.send_error(404)
            return
        data = (WEB / asset).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", MIME_TYPES[".html"])
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        try:
            data = self._read_json()
            if self.path == "/api/config":
                cfg = save_local_config(data)
                load_env(ENV_FILE)
                self._json(200, {"ok": True, "api_key_set": bool(cfg.get("OPENAI_API_KEY", "").strip())})
                return
            if self.path == "/api/generate":
                prompt = str(data.get("prompt", "")).strip()
                if not prompt:
                    raise ValueError("请先填写图片描述。")
                with LOCK:
                    target = unique_target("generated")
                    path, status = generate(prompt, target)
                record_image(path, prompt, "generate")
                self._json(200, {"ok": True, "name": path.name, "url": f"/output/{path.name}", "http_status": status})
                return
            if self.path == "/api/edit":
                prompt = str(data.get("prompt", "")).strip()
                if not prompt:
                    raise ValueError("请先填写编辑要求。")
                chosen = data.get("image_name")
                uploaded = data.get("image")
                if bool(chosen) == bool(uploaded):
                    raise ValueError("请选择图库中的一张图片，或上传一张图片。")
                if chosen:
                    name = Path(str(chosen)).name
                    source = (OUT / name).resolve()
                    if name != chosen or source.parent != OUT.resolve() or not source.is_file():
                        raise ValueError("所选图片无效，请刷新图库后重试。")
                    inputs = [source]
                else:
                    filename = Path(str(uploaded.get("name", "upload.png"))).name
                    suffix = Path(filename).suffix.lower()
                    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
                        raise ValueError("只支持 PNG、JPG 或 WebP 图片。")
                    try:
                        blob = base64.b64decode(uploaded.get("data", ""), validate=True)
                    except Exception as exc:
                        raise ValueError("上传图片数据无效。") from exc
                    if len(blob) > 25 * 1024 * 1024:
                        raise ValueError("单张上传图片不能超过 25 MB。")
                    if not (blob.startswith(b"\x89PNG\r\n\x1a\n") or blob.startswith(b"\xff\xd8\xff") or blob.startswith(b"RIFF") and blob[8:12] == b"WEBP"):
                        raise ValueError("文件内容不是有效的 PNG、JPG 或 WebP 图片。")
                    temp = OUT / f".upload_{threading.get_ident()}{suffix}"
                    temp.write_bytes(blob)
                    inputs = [temp]
                try:
                    with LOCK:
                        target = unique_target("edited")
                        path, status = edit(prompt, inputs, target)
                finally:
                    if uploaded:
                        temp.unlink(missing_ok=True)
                record_image(path, prompt, "edit")
                self._json(200, {"ok": True, "name": path.name, "url": f"/output/{path.name}", "http_status": status})
                return
            self.send_error(404)
        except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
            self._json(400, {"ok": False, "error": str(exc)})
        except Exception as exc:  # Surface unexpected provider/client errors to the UI.
            self._json(500, {"ok": False, "error": f"服务内部错误：{type(exc).__name__}: {exc}"})


def main() -> None:
    load_env(ENV_FILE)
    host, port = "127.0.0.1", int(os.environ.get("IMAGE_UI_PORT", "8765"))
    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"图片工作台运行于 {url} （仅本机可访问；Ctrl+C 停止）")
    try:
        webbrowser.open(url)
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已关闭图片工作台。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
