# 本地对话式图片助手

本目录是独立 Git 仓库。Python 源码和测试位于 `src/`；`.env` 保存本机 API Key，输出图片保存在 `output/`，两者均不会纳入 Git。

图片助手使用 `.env` 中的 FoxCode 配置，通过 OpenAI 兼容图片接口生成或编辑图片。API Key 只从本机 `.env` 读取。

## 启动对话

在本目录运行：

```powershell
python .\src\image_agent.py
```

## 网页工作台

Windows 用户可双击 `start.bat` 一键启动；也可以在终端运行：

```powershell
python .\src\server.py
```

服务会打开本地网页 `http://127.0.0.1:8765`。页面可切换生成/编辑，选择模型或自定义模型，设置 API Key、基础 URL、生成/编辑 URL、尺寸和质量；编辑时可上传图片或从图库选取。Key 只保存在本地 `.env`，网页不回显已有 Key。服务仅绑定 `127.0.0.1`，供本机使用。

可以直接用中文描述操作：

```text
生成一张雨夜赛博朋克街景
编辑上一张，把背景改成日落海边
编辑第 2 张，移除桌上的杯子
修改 sci_fi_personal_computer.png，让机箱变成白色
```

输入 `/参考` 可通过文件选择器一次添加多张参考图片；之后的生成请求会基于参考图创作新图，编辑请求会把目标图和参考图一起提交。输入 `/清除参考` 清除参考图。参考图不会改动，也不会自动加到输出图库。

`/list` 显示输出目录图片；`/history` 显示最近记录，`/history 文件名` 或 `/history 第 2 张` 显示图片的修改历史和来源链；`/help` 显示示例；`/quit` 退出。图片编号按输出目录里最近修改时间排序，1 是最新图片。编辑会另存为 `edited_*.png`，保留原图。也可以在编辑指令中给出本地图片完整路径。

图片历史保存在 `output/image_history.json`，每条编辑记录包含提示词、来源图片、参考图片和前序提示词上下文。后续编辑会读取最多三层前序提示词，帮助图像模型延续修改方向。网页工作台与对话 agent 共用同一输出目录和历史文件。

如果编辑指令没有唯一指向目标图片，助手会列出图片并询问编号、文件名或完整路径。助手仅会编辑 `output/` 中可识别的图片或你明确提供的图片路径。

## 命令行单次调用

生成：

```powershell
python .\src\generate_image.py "一张未来感城市夜景" -o .\output\city.png
```

编辑：

```powershell
python .\src\generate_image.py "把背景改成日落海边，主体保持不变" --edit .\output\city.png -o .\output\city_sunset.png
```

编辑接口使用 `/v1/images/edits`、multipart/form-data 和图片字段 `image`。多张参考图片可重复指定 `--edit image1.png image2.png`。

## 配置

`.env` 中的默认项按接口示例设置为 `https://dm-fox.rjj.cc/codex/v1/images/generations`，模型 `gpt-image-2.5`，尺寸 `1536x1024`，质量 `high`。可按服务商要求修改模型、尺寸、质量与 API Key。

首次配置可复制 `.env.example` 为 `.env` 并填写密钥。当前 `.env` 保留在本地，不会提交。

## 测试

```powershell
python -m unittest discover -s .\src -p "test_*.py" -v
```

需要 Python 3.10+ 和 Windows `curl.exe`。生图结果是视觉图片，不是可制造 CAD 模型。
