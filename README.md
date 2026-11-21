# BiliBrief · B 站视频速读

BiliBrief 是一个本地 MCP 服务。把 B 站视频链接发给接入它的 AI，就能读一份中文速览，点要点旁的时间戳回到原片。讲解、访谈优先读字幕，软件演示和课件还可以查看指定片段的画面。[查看一份真实视频的 30 秒速读](examples/snowboarding.md)

## 安装

准备 Git 和 Python 3.11 或更高版本。需要抽帧时，安装 FFmpeg 并确认 `ffmpeg -version` 可以运行。在 Windows PowerShell 中执行以下命令。

```powershell
git clone https://github.com/maile456/BiliBrief.git
cd BiliBrief
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

如果还想阅读没有可用字幕的视频，安装本地语音转写组件。首次转写会下载语音模型，之后可以复用本地模型和转写缓存。

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[asr]"
```

## 接入 MCP 客户端

在项目根目录运行下面这行 PowerShell，生成使用本机绝对路径的 MCP 配置。把输出的 `bilibrief` 项加入客户端的 `mcpServers` 配置即可。

```powershell
@{ mcpServers = @{ bilibrief = @{ command = (Resolve-Path .\.venv\Scripts\python.exe).Path; args = @('-m', 'bilibrief') } } } | ConvertTo-Json -Depth 5
```

对于使用其他配置格式的客户端，选择 **stdio**，将启动命令设为上一步输出的 Python 绝对路径，参数依次填 `-m` 和 `bilibrief`。macOS 和 Linux 的虚拟环境解释器位于 `.venv/bin/python`。也可以让客户端直接启动虚拟环境里的 `bilibrief` 命令。[Codex MCP 配置文档](https://developers.openai.com/codex/mcp/)

## 怎么用

> 用 BiliBrief 速读这个视频：〈粘贴链接〉。用一句话讲结论，再给我三个要点，每点带播放时间。最后挑一个最值得点开的片段。

支持 BV 号、av 号、B 站视频长链接和 b23.tv 短链。多分 P 视频可以粘贴含 `?p=2` 的原链接。

| 工具 | 适用场景 |
| --- | --- |
| `bili_digest` | 整片速读。默认 `visual="auto"` 优先口述，`visual="always"` 附抽帧，`visual="never"` 只读文字。 |
| `bili_window` | 给定起止时间（秒），查看一小段的字幕和抽样画面，例如“2 分钟时屏幕上演示了什么？” |
| `bili_search` | 按关键词查找字幕或转写中的原句和播放时间。 |
| `bili_resolve` | 确认视频、分 P 标题和时长。 |

默认由当前聊天的 AI 阅读证据并组织答案。看到“本地语音转写”或“平台自动字幕”时，可点时间戳复核数字和专有名词。短暂的动作、弹窗或某一行代码可以用 `bili_window` 缩小时间范围查看。显示截图需要客户端支持 MCP 图片内容。

## 可选配置

可将 [config.example.env](config.example.env) 复制为项目根目录的 `.env`。BiliBrief 沿用早期版本的 `VIDBRIEF_*` 变量和缓存。Windows 默认缓存路径为 `%LOCALAPPDATA%\VidBrief\cache`。用 `VIDBRIEF_CACHE_DIR` 指定其他目录，用 `VIDBRIEF_WHISPER_MODEL` 选择语音模型。

个别视频的字幕需要登录。可在本机通过 `VIDBRIEF_COOKIES_FILE` 指向自己的 Cookie 文件。

若希望由服务端先生成中文摘要，可以设置 `VIDBRIEF_LLM_BASE_URL`（例如服务的 `/v1` 地址）、`VIDBRIEF_LLM_MODEL` 以及该服务所需的 `VIDBRIEF_LLM_API_KEY`。启用后，视频标题和部分文字证据会发送到该地址。地址留空时，服务端返回本地摘录。
