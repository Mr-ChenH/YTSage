<div align="center">
<img src="../branding/svg/ytsage-wordmark.svg" width="180" height="180" alt="YTSage 图标">

# YTSage

**带现代 Web UI 的自托管 yt-dlp 下载服务。**

本 fork 基于上游项目 [oop7/YTSage](https://github.com/oop7/YTSage) 修改，并调整为更适合自托管 Web 服务的使用流程。

支持分析媒体链接、下载视频/音频/字幕、管理播放列表和任务、浏览下载文件，并在浏览器中播放本地媒体。

<img src="../branding/screenshots/main.png" width="800" alt="YTSage Web UI 截图">

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-1f2937?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-server-1f2937?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-web_UI-1f2937?style=for-the-badge&logo=react&logoColor=white)](https://react.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-1f2937?style=for-the-badge&logo=opensource&logoColor=white)](https://opensource.org/licenses/MIT)

<a href="#功能">功能</a> -
<a href="#快速开始">快速开始</a> -
<a href="#配置">配置</a> -
<a href="#开发">开发</a> -
<a href="#api">API</a> -
<a href="#故障排查">故障排查</a>

</div>

---

<a id="概览"></a>
## 概览

YTSage 当前重点是服务端体验：FastAPI 服务、构建后的 React Web UI、持久化任务/历史记录存储，以及围绕 `yt-dlp` 和 `ffmpeg` 的本地媒体管理能力。

默认包入口会启动 Web 服务。UI 由后端直接提供，因此启动服务后通过浏览器使用 YTSage，而不是打开桌面窗口。

当前技术栈：

- 后端：FastAPI、Uvicorn、Pydantic、SQLite 存储
- 下载器：yt-dlp
- 媒体处理：ffmpeg，必要时通过 `imageio-ffmpeg` 提供
- 前端：React、Vite、ArtPlayer
- 运行设置：环境变量加 `server-settings.json`

<a id="功能"></a>
## 功能

### 下载工作台

- 分析 yt-dlp 支持的 URL。
- 下载视频、音频或字幕。
- 从分析出的格式列表中选择格式。
- 选择视频容器：`mp4`、`webm`、`mkv`。
- 选择音频输出：`mp3`、`m4a`、`opus`、`flac`、`wav`。
- 从分析结果中选择字幕语言。
- 支持合并字幕、保存缩略图、保存描述、嵌入章节和音频标准化。
- 为单个任务配置代理地址。
- 为单个任务配置并发片段下载。
- 使用服务默认视频清晰度进行自动格式选择。

### 播放列表处理

- 分析播放列表，并在创建任务前选择具体条目。
- 播放列表支持页码分页。
- 每个条目都有状态：未下载、正在下载、已下载、错误。
- 在 yt-dlp 支持时，单个条目失败不会阻止后续条目继续下载。
- 可在原任务记录中重试失败的播放列表条目。

### 任务和历史记录

- 基于队列执行下载任务，并支持配置队列并发。
- 通过 WebSocket 实时更新任务状态，并保留轮询刷新。
- 支持取消、删除和清理已结束任务。
- 已完成和失败的下载会写入历史记录。
- 服务重启后会标记被中断的任务。

### 文件库

- 以左侧目录树和右侧媒体表格浏览下载目录。
- 支持搜索和媒体文件分页。
- 单文件下载支持 HTTP Range。
- 可将选中目录下载为 ZIP。
- 可导出目录清单，格式支持 `aria2`、`txt`、`json`。
- aria2 清单内置多连接和断点续传参数，适合大目录批量下载。

### 播放页面

- 独立播放页面，不占用文件浏览页空间。
- 类 YouTube 布局：左侧主播放器，右侧播放列表。
- 可选择下载目录作为播放队列来源。
- 使用 ArtPlayer 播放本地视频和音频文件。
- 播放器内置倍速、全屏、网页全屏、快捷键和视频画中画支持。

### 设置和系统

- 保存文件名模板预设或自定义 yt-dlp 输出模板。
- 保存默认视频清晰度。
- 管理 default、Bilibili、YouTube 三类 Cookies 配置。
- 查看服务健康状态、下载/配置路径、队列并发、认证状态、yt-dlp 版本和 ffmpeg 状态。
- 在系统页安装或更新运行依赖。

<a id="快速开始"></a>
## 快速开始

### 从 PyPI 安装

```bash
pip install ytsage
```

启动服务：

```bash
ytsage
```

打开 Web UI：

```text
http://127.0.0.1:8080
```

### 从源码运行

```bash
git clone https://github.com/oop7/YTSage.git
cd YTSage
pip install .
ytsage
```

也可以直接运行服务模块：

```bash
python -m ytsage.server.app
```

<a id="配置"></a>
## 配置

YTSage 从环境变量读取配置。本地开发时，也会自动读取项目根目录下的 `.env` 文件，并且不会覆盖已经在 shell 中显式设置的环境变量。

创建本地 `.env` 文件：

```powershell
Copy-Item .env.example .env
```

`.env.example` 默认内容：

```text
YTSAGE_CONFIG_DIR=.dev-data/config
YTSAGE_DOWNLOAD_DIR=.dev-data/downloads
YTSAGE_QUEUE_CONCURRENCY=2
YTSAGE_HOST=127.0.0.1
YTSAGE_PORT=8080
# YTSAGE_AUTH_TOKEN=change-me
```

支持的变量：

| 变量 | 用途 | 默认值 |
|---|---|---|
| `YTSAGE_CONFIG_DIR` | 配置、数据库、Cookies 和服务设置目录 | 平台配置目录 |
| `YTSAGE_DOWNLOAD_DIR` | 下载输出目录 | 用户下载目录/YTSage |
| `YTSAGE_QUEUE_CONCURRENCY` | 并发 worker 数 | `2` |
| `YTSAGE_HOST` | 服务绑定地址 | `127.0.0.1` |
| `YTSAGE_PORT` | 服务端口 | `8080` |
| `YTSAGE_AUTH_TOKEN` | 可选 API/UI Bearer Token | 未设置 |
| `YTSAGE_AUTO_INSTALL_DEPS` | 启动时自动安装缺失的 yt-dlp/ffmpeg 辅助依赖 | `1` |

持久化 UI 设置保存在 `YTSAGE_CONFIG_DIR` 下的 `server-settings.json`。

<a id="使用"></a>
## 使用

### 创建下载任务

1. 打开 Web UI。
2. 在下载页面粘贴 URL。
3. 点击分析。
4. 选择视频、音频或字幕模式。
5. 配置输出选项。
6. 如果是播放列表，在播放列表表格中选择要下载的条目。
7. 点击创建下载任务。

### 播放已下载媒体

1. 打开文件页并选择目录。
2. 点击媒体文件上的播放，或直接进入播放页。
3. 在播放页中选择播放目录，将该目录加载为播放队列。

### 使用目录清单

文件页可以为选中的目录导出下载清单。默认格式适用于 aria2：

```bash
aria2c -i folder.aria2.txt
```

清单包含下载 URL 和 aria2 参数，例如：

```text
split=8
max-connection-per-server=8
continue=true
```

也可以手动修改 URL 获取其它格式：

```text
/api/folders/manifest?folder=<folder>&format=txt
/api/folders/manifest?folder=<folder>&format=json
/api/folders/manifest?folder=<folder>&format=aria2
```

<a id="开发"></a>
## 开发

### 后端

Windows PowerShell 可使用辅助脚本：

```powershell
.\scripts\dev-server.ps1
```

或者创建 `.env` 后手动启动：

```bash
python -m ytsage.server.app
```

### 前端

安装前端依赖：

```bash
npm --prefix frontend install
```

运行 Vite 开发服务：

```bash
npm --prefix frontend run dev
```

构建生产前端：

```bash
npm --prefix frontend run build
```

后端从 `ytsage/server/static/` 提供静态资源。前端修改后，需要把构建结果复制到服务端静态目录：

```bash
rm -rf ytsage/server/static/*
cp -R frontend/dist/* ytsage/server/static/
```

在 PowerShell 中使用等价的删除和复制命令。

### 验证

提交前建议运行：

```bash
python -m py_compile ytsage/server/app.py ytsage/server/models.py ytsage/server/services/download_service.py
npm --prefix frontend run build
```

<a id="api"></a>
## API 概览

常用接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/health` | 服务、依赖和路径健康状态 |
| `GET` | `/api/settings` | UI 可见的运行设置 |
| `POST` | `/api/settings/filename-template` | 保存文件名模板和默认清晰度 |
| `POST` | `/api/settings/cookies` | 保存或清除某个平台的 Cookies |
| `POST` | `/api/dependencies/update` | 更新 yt-dlp 和 ffmpeg 辅助依赖 |
| `POST` | `/api/analyze` | 分析媒体 URL |
| `POST` | `/api/tasks` | 创建下载任务 |
| `GET` | `/api/tasks` | 列出任务 |
| `POST` | `/api/tasks/{task_id}/cancel` | 取消任务 |
| `POST` | `/api/tasks/{task_id}/retry-playlist-item/{playlist_index}` | 重试一个失败的播放列表条目 |
| `GET` | `/api/history` | 列出下载历史 |
| `GET` | `/api/files` | 列出文件和目录 |
| `GET` | `/api/files/{file_id}/download` | 下载文件，支持 Range |
| `GET` | `/api/files/{file_id}/stream` | 流式播放文件，支持 Range |
| `GET` | `/api/folders/download` | 将目录下载为 ZIP |
| `GET` | `/api/folders/manifest` | 导出目录清单，支持 aria2/txt/json |
| `WS` | `/api/events` | 实时任务事件 |

如果设置了 `YTSAGE_AUTH_TOKEN`，API 请求需要携带 `Authorization: Bearer <token>`。浏览器中的 WebSocket 和文件链接也可在需要时使用 `?token=<token>`。

<a id="故障排查"></a>
## 故障排查

### 缺少 yt-dlp 或 ffmpeg

打开系统页并点击更新依赖。除非设置了 `YTSAGE_AUTO_INSTALL_DEPS=0`，服务启动时也会尝试安装缺失的运行依赖。

### 分析结果只有元数据，没有格式列表

这可能发生在需要登录、年龄/风险确认、区域限制，或者提取器延迟到下载阶段才解析格式的场景。请在设置页为目标站点配置 Cookies，并在系统页更新 yt-dlp。

### 高质量视频下载后出现独立音视频流

很多站点会把高质量视频和音频分开提供。合并这些流需要 FFmpeg。请在系统页检查 ffmpeg 状态并更新依赖。

### 浏览器看不到最新 UI

重新构建前端并重启服务后，请强制刷新浏览器页面。构建后的资源文件名每次可能变化。

### Ctrl+C 关闭服务

打包后的 `ytsage` 命令使用了静默 Uvicorn 服务包装器，Ctrl+C 会优雅关闭服务，不再重放 `KeyboardInterrupt` 堆栈。如果直接运行 Uvicorn，你本地的 Uvicorn/Python 组合仍可能打印自己的关闭堆栈。

<a id="项目结构"></a>
## 项目结构

```text
YTSage/
├── frontend/                  # React/Vite Web UI
│   └── src/
│       ├── api/               # API 类型和客户端
│       ├── i18n/              # Web UI 国际化资源
│       ├── main.tsx           # 主单页应用
│       └── styles.css         # UI 样式
├── scripts/
│   └── dev-server.ps1         # Windows 本地开发服务脚本
├── ytsage/
│   ├── core/                  # 历史/核心辅助模块
│   └── server/
│       ├── app.py             # FastAPI 应用和路由
│       ├── config.py          # 环境变量和 .env 配置加载
│       ├── models.py          # API 模型
│       ├── static/            # FastAPI 提供的构建后前端
│       └── services/          # 分析、下载、文件、任务、设置服务
├── .env.example               # 本地服务配置模板
├── pyproject.toml             # Python 包元数据
└── README.md
```

<a id="贡献"></a>
## 贡献

1. Fork 本仓库。
2. 创建功能分支。
3. 保持改动聚焦，并在行为变化时更新 README/API 类型。
4. 运行后端编译检查和前端构建。
5. 提交 Pull Request。

<a id="许可证"></a>
## 许可证

本项目使用 MIT License。详见 [LICENSE](../LICENSE)。

<a id="致谢"></a>
## 致谢

YTSage 基于以下项目构建：

- [yt-dlp](https://github.com/yt-dlp/yt-dlp)：媒体提取和下载
- [FFmpeg](https://ffmpeg.org/)：封装和媒体转换
- [FastAPI](https://fastapi.tiangolo.com/) 与 [Uvicorn](https://www.uvicorn.org/)：Web 服务
- [React](https://react.dev/) 与 [Vite](https://vite.dev/)：Web UI
- [ArtPlayer](https://artplayer.org/)：浏览器播放

## 免责声明

本工具仅供个人使用。请遵守站点服务条款、版权法律和创作者权益。
