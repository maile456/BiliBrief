# BiliBrief · B 站字幕

把 B 站链接交给 AI，BiliBrief 只返回平台字幕。如何分析、总结或排版，由你在聊天里的提示词决定。

`bili_subtitles(url)` 接受 BV 号、av 号、视频长链接和 b23.tv 短链。多分 P 视频用 `?p=2` 指定分 P。成功时返回一份完整字幕，按原字幕的顺序分行。当前可访问的字幕为空时，返回一句提示。

## 安装与接入

需要 Python 3.11+。在 Windows PowerShell 中运行以下命令。

```powershell
git clone https://github.com/maile456/BiliBrief.git
cd BiliBrief
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
(Resolve-Path .\.venv\Scripts\python.exe).Path
```

在 MCP 客户端添加一个 **stdio** 服务，启动命令填写最后一行输出的 Python 绝对路径，参数为 `["-m", "bilibrief"]`。macOS 和 Linux 使用 `.venv/bin/python`。

部分平台字幕需要登录。可在项目根目录的 `.env` 中将 `VIDBRIEF_COOKIES_FILE` 设为你自己的 Cookie 文件路径，也可用 `VIDBRIEF_COOKIES_FROM_BROWSER` 指定本机浏览器。

## 使用

> 读取〈B 站链接〉的字幕，请告诉我作者想解决什么问题，举了哪些例子。
