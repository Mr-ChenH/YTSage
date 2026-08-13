<div align="center">
  <img src="branding/svg/ytsage-wordmark.svg" width="180" height="180" alt="YTSage">

# YTSage

**基于 yt-dlp 的自托管音视频下载与媒体管理服务**

在浏览器中分析媒体链接，下载视频、音频、字幕和播放列表，并集中管理任务、历史记录与本地媒体文件。

[![Docker Image](https://img.shields.io/badge/Docker-xmoli%2Fytsage-2496ED?logo=docker&logoColor=white)](https://hub.docker.com/r/xmoli/ytsage)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Web_API-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

[快速开始](#快速开始) · [功能](#功能) · [配置](#配置) · [更新](#更新) · [常见问题](#常见问题) · [开发](#本地开发)

<img src="branding/screenshots/main.png" width="900" alt="YTSage Web 界面">
</div>

## 项目简介

YTSage 将 [yt-dlp](https://github.com/yt-dlp/yt-dlp) 和 [FFmpeg](https://ffmpeg.org/) 封装为一个可自托管的 Web 服务。后端负责链接分析、下载队列、任务状态和文件访问，前端提供下载工作台、媒体文件库及在线播放器。

项目适合以下场景：

- 在 NAS、家庭服务器或 Linux 主机上部署统一的下载服务
- 从电脑或手机浏览器提交下载任务
- 下载视频、提取音频、保存字幕或选择播放列表条目
- 通过浏览器管理、下载和播放服务器上的媒体文件
- 使用 Docker 持久化配置、历史记录、Cookies 和下载内容

> [!NOTE]
> 本项目基于上游 [oop7/YTSage](https://github.com/oop7/YTSage) 修改，当前版本侧重自托管 Web 服务体验。

## 功能

### 下载与格式处理

- 支持 yt-dlp 可解析的媒体链接
- 下载视频、音频或字幕
- 选择具体格式、视频封装格式和音频输出格式
- 支持 `mp4`、`webm`、`mkv` 视频容器
- 支持 `mp3`、`m4a`、`opus`、`flac`、`wav` 音频格式
- 保存缩略图、描述信息并嵌入章节
- 字幕语言选择与字幕合并
- 音频标准化、下载限速、代理和分片并发设置
- 自定义 yt-dlp 文件名模板和默认视频清晰度

### 播放列表与任务

- 分析播放列表并选择需要下载的条目
- 显示播放列表条目的下载状态
- 单个条目失败时继续处理后续内容
- 单独重试失败的播放列表条目
- 队列化执行任务，支持调整服务并发数
- 通过 WebSocket 实时更新任务进度
- 支持取消、删除和清理任务记录
- 服务重启后自动标记被中断的任务

### 文件与播放

- 目录树、文件搜索和分页浏览
- 单文件下载与 HTTP Range 请求
- 将整个目录打包为 ZIP 下载
- 导出 `aria2`、`txt` 或 `json` 格式的目录清单
- 使用 ArtPlayer 在线播放已下载的视频和音频
- 按目录生成播放队列
- 支持倍速、画中画、快捷键及全屏播放

### 配置与安全

- SQLite 持久化任务和下载历史
- 管理默认、Bilibili 和 YouTube Cookies
- 可选 Bearer Token 访问控制
- 查看服务、目录、yt-dlp 和 FFmpeg 健康状态
- 在系统页面更新 yt-dlp 和 FFmpeg 辅助依赖
- 中文和英文 Web 界面

## 快速开始

推荐使用 Docker Compose 部署。镜像已经包含前端、后端、yt-dlp 和 FFmpeg，不需要额外安装运行环境。

### Docker Compose

创建 `docker-compose.yml`：

```yaml
services:
  ytsage:
    image: xmoli/ytsage:latest
    container_name: ytsage-server
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      TZ: Asia/Shanghai
      # 服务暴露到非可信网络时建议启用：
      # YTSAGE_AUTH_TOKEN: change-this-token
    volumes:
      - ./data/config:/config
      - ./data/downloads:/downloads
```

启动服务：

```bash
docker compose up -d
```

浏览器打开：

```text
http://服务器地址:8080
```

查看容器状态和日志：

```bash
docker compose ps
docker compose logs -f
```

### Docker CLI

```bash
docker run -d \
  --name ytsage-server \
  --restart unless-stopped \
  -p 8080:8080 \
  -e TZ=Asia/Shanghai \
  -v "$(pwd)/data/config:/config" \
  -v "$(pwd)/data/downloads:/downloads" \
  xmoli/ytsage:latest
```

### 从源码构建镜像

```bash
git clone https://github.com/Mr-ChenH/YTSage.git
cd YTSage
docker compose up -d --build
```

## 数据持久化

容器使用两个持久化目录：

| 容器路径 | Compose 默认映射 | 内容 |
|---|---|---|
| `/config` | `./data/config` | SQLite 数据库、Cookies 和界面设置 |
| `/downloads` | `./data/downloads` | 下载完成及下载中的媒体文件 |

删除或重新创建容器不会删除宿主机上的这两个目录。升级前建议备份 `data/config`。

容器启动时，入口脚本会自动创建挂载目录并将其调整为应用用户可写。入口脚本完成初始化后，会立即降权运行 YTSage；应用进程不会以 root 身份常驻：

```text
UID=10001
GID=10001
```

因此使用默认 Docker 或 Compose 配置时，不需要手动执行 `mkdir`、`chown` 或 `chmod`。如果通过 `user:` 或 `docker run --user` 强制覆盖容器用户，自动权限初始化将无法执行，此时需要自行保证挂载目录可写。

## 配置

所有配置均为可选环境变量。Docker 镜像已经提供适合容器运行的默认值。

| 环境变量 | 默认值 | 说明 |
|---|---:|---|
| `YTSAGE_HOST` | `0.0.0.0` | 服务监听地址 |
| `YTSAGE_PORT` | `8080` | 容器内服务端口 |
| `YTSAGE_CONFIG_DIR` | `/config` | 配置、数据库和 Cookies 目录 |
| `YTSAGE_DOWNLOAD_DIR` | `/downloads` | 下载文件目录 |
| `YTSAGE_QUEUE_CONCURRENCY` | `2` | 同时执行的任务数，可选范围 `1` 至 `8` |
| `YTSAGE_AUTH_TOKEN` | 未设置 | 可选 Bearer Token；未设置时不启用认证 |
| `YTSAGE_AUTO_INSTALL_DEPS` | `1` | 是否在启动时尝试补充缺失的运行依赖 |
| `TZ` | `UTC` | 容器时区，使用 IANA 时区名称 |

通常无需设置目录和端口环境变量，只要保持以下映射即可：

```yaml
ports:
  - "8080:8080"
volumes:
  - ./data/config:/config
  - ./data/downloads:/downloads
```

如需使用其他宿主机端口，只修改冒号左侧：

```yaml
ports:
  - "8090:8080"
```

此时访问地址为 `http://服务器地址:8090`，容器内端口仍为 `8080`。

### 启用访问令牌

服务只在可信局域网使用时可以不设置令牌。部署到公网或共享网络时，应配置强随机令牌：

```yaml
environment:
  TZ: Asia/Shanghai
  YTSAGE_AUTH_TOKEN: "请替换为足够长的随机字符串"
```

重建容器后，在 Web 界面顶部或设置页输入相同令牌。API 客户端应发送：

```http
Authorization: Bearer <token>
```

> [!IMPORTANT]
> Bearer Token 不能替代 HTTPS。通过公网访问时，请在 YTSage 前部署支持 WebSocket 的 HTTPS 反向代理。

### Cookies

需要登录、年龄确认或会员权限的内容通常需要 Cookies。可在 Web 界面的“设置”页面上传 Netscape 格式的 Cookies 文件，并选择：

- `default`：所有未匹配专用配置的网站
- `youtube`：YouTube
- `bilibili`：哔哩哔哩

Cookies 保存在 `/config`，请将该目录视为敏感数据，不要提交到 Git 或公开分享。

## 使用流程

1. 打开“下载”页面并粘贴媒体链接。
2. 点击“分析”，等待返回媒体信息和可用格式。
3. 选择视频、音频或字幕模式及输出选项。
4. 如果链接是播放列表，选择需要下载的条目。
5. 创建任务，并在“任务”页面查看实时进度。
6. 下载完成后，在“文件”或“播放”页面管理媒体。

对于需要在其他设备批量下载的目录，可在文件页面导出 aria2 清单：

```bash
aria2c -i folder.aria2.txt
```

## 更新

Compose 使用 `xmoli/ytsage:latest`，更新时无需修改配置文件：

```bash
docker compose pull
docker compose up -d
```

确认新容器健康后，可清理不再使用的旧镜像：

```bash
docker image prune
```

如果需要固定版本以避免自动切换，可以使用版本标签，例如：

```yaml
image: xmoli/ytsage:5.4.6
```

## 健康检查

镜像内置 Docker 健康检查：

```bash
docker inspect --format '{{.State.Health.Status}}' ytsage-server
```

也可以直接请求接口：

```bash
curl http://127.0.0.1:8080/api/health
```

正常响应会包含：

- 配置目录和下载目录是否可写
- yt-dlp 与 FFmpeg 版本
- 当前任务并发数
- 是否已配置访问令牌

## 常见问题

### 容器启动后显示 `unhealthy`

先检查日志和健康接口：

```bash
docker compose logs --tail=100 ytsage
curl http://127.0.0.1:8080/api/health
```

最常见原因是挂载目录所在文件系统不允许容器修改所有者，例如某些只读挂载或受限网络文件系统。默认本地 bind mount 会由容器入口脚本自动初始化权限；如果配置了 `user:`、`--user` 或只读挂载，则需要自行确保 `/config` 和 `/downloads` 对指定用户可写。

### `8080` 端口已被占用

将宿主机端口改为其他值：

```yaml
ports:
  - "8081:8080"
```

然后执行：

```bash
docker compose up -d --force-recreate
```

### 链接能分析标题，但没有具体格式

常见原因包括登录限制、年龄或风险确认、地区限制，以及站点只在下载阶段解析格式。请尝试：

1. 在设置页上传对应站点的 Cookies。
2. 在系统页更新 yt-dlp。
3. 使用通用的 `best` 或 `bestaudio` 格式继续下载。

### 高画质视频没有声音或需要合并

许多站点将高画质视频流和音频流分开提供。YTSage 使用 FFmpeg 合并它们。请在系统页或 `/api/health` 中确认 FFmpeg 可用。

### 反向代理后任务进度不更新

任务实时状态使用 WebSocket。请确认反向代理允许升级连接，并正确转发 `/api/events`。

### 更新后仍显示旧界面

确认容器使用的是新镜像，然后强制刷新浏览器缓存：

```bash
docker compose pull
docker compose up -d --force-recreate
docker compose images
```

## API

FastAPI 自动生成交互式 API 文档：

```text
http://服务器地址:8080/docs
```

常用接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/health` | 服务和依赖健康状态 |
| `GET` | `/api/settings` | 当前运行配置 |
| `POST` | `/api/analyze` | 分析媒体链接 |
| `POST` | `/api/tasks` | 创建下载任务 |
| `GET` | `/api/tasks` | 获取任务列表 |
| `POST` | `/api/tasks/{id}/cancel` | 取消任务 |
| `GET` | `/api/history` | 获取下载历史 |
| `GET` | `/api/files` | 获取文件列表 |
| `GET` | `/api/files/{id}/download` | 下载文件 |
| `GET` | `/api/files/{id}/stream` | 流式读取媒体文件 |
| `GET` | `/api/folders/download` | 将目录下载为 ZIP |
| `GET` | `/api/folders/manifest` | 导出目录清单 |
| `WS` | `/api/events` | 实时任务事件 |

## 非 Docker 安装

需要 Python `3.11` 至 `3.14`，并建议预先安装 FFmpeg。应用自身默认使用 `/config` 和 `/downloads`，因此裸机运行前应显式指定当前用户可写的目录：

```bash
python -m venv .venv
source .venv/bin/activate
pip install ytsage

export YTSAGE_CONFIG_DIR="$HOME/.config/ytsage"
export YTSAGE_DOWNLOAD_DIR="$HOME/Downloads/YTSage"
export YTSAGE_HOST=127.0.0.1
ytsage
```

默认端口为 `8080`，按上述配置可通过以下地址访问：

```text
http://127.0.0.1:8080
```

从源码安装：

```bash
git clone https://github.com/Mr-ChenH/YTSage.git
cd YTSage
python -m venv .venv
source .venv/bin/activate
pip install .
cp .env.example .env
ytsage
```

`.env.example` 已将配置和下载目录设置到项目内的 `.dev-data`，并只监听 `127.0.0.1`。按需修改后再启动服务。

## 本地开发

后端：

```bash
python -m venv .venv
source .venv/bin/activate
pip install .
cp .env.example .env
python -m ytsage.server.app
```

前端：

```bash
npm --prefix frontend ci
npm --prefix frontend run dev
```

构建生产前端：

```bash
npm --prefix frontend run build
rm -rf ytsage/server/static/*
cp -R frontend/dist/* ytsage/server/static/
```

提交前至少执行：

```bash
python -m compileall -q ytsage
npm --prefix frontend run build
docker compose config
```

## 项目结构

```text
YTSage/
├── frontend/                 # React、Vite 和 ArtPlayer 前端
├── scripts/                  # 本地开发辅助脚本
├── ytsage/
│   └── server/
│       ├── app.py            # FastAPI 应用和接口
│       ├── config.py         # 环境变量与目录配置
│       ├── models.py         # API 数据模型
│       ├── services/         # 分析、下载、任务、文件和存储服务
│       └── static/           # 后端提供的前端构建产物
├── Dockerfile               # 多阶段镜像构建
├── docker-compose.yml       # Docker Compose 部署配置
└── pyproject.toml           # Python 包与版本信息
```

## 技术栈

- [FastAPI](https://fastapi.tiangolo.com/) / [Uvicorn](https://www.uvicorn.org/)：Web 服务
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)：媒体信息提取与下载
- [FFmpeg](https://ffmpeg.org/)：音视频合并与格式处理
- [React](https://react.dev/) / [Vite](https://vite.dev/)：Web 界面
- [ArtPlayer](https://artplayer.org/)：浏览器媒体播放
- SQLite：任务与历史记录持久化

## 贡献

欢迎提交 Issue 和 Pull Request。提交代码前请确保：

- 改动范围清晰，不包含无关格式化或重构
- 行为变化同步更新文档和前端 API 类型
- Python 模块可以编译
- 前端可以完成生产构建
- Docker Compose 配置可以正常解析

## 致谢

感谢 [oop7/YTSage](https://github.com/oop7/YTSage) 上游项目，以及 yt-dlp、FFmpeg、FastAPI、React、Vite 和 ArtPlayer 等开源项目。

## 许可证

本项目采用 [MIT License](LICENSE)。

## 免责声明

本工具仅用于合法的个人下载和媒体管理。使用者应自行确认对目标内容拥有下载、保存和使用权限，并遵守相关网站服务条款、所在地法律法规、版权及创作者权益。项目维护者不对滥用行为承担责任。
