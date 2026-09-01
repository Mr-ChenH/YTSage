#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR/.." rev-parse --show-toplevel 2>/dev/null || true)"
IMAGE_NAME="${IMAGE_NAME:-xmoli/ytsage}"
GIT_REMOTE="${GIT_REMOTE:-origin}"
PULL_SOURCE=1
DRY_RUN=0

usage() {
    cat <<'EOF'
用法：scripts/publish-docker.sh [选项]

拉取当前分支的最新代码，从 pyproject.toml 读取版本，构建并推送：
  <镜像>:<版本>
  <镜像>:latest

选项：
  --image <名称>    镜像仓库，默认 xmoli/ytsage
  --remote <名称>   Git 远端，默认 origin
  --no-pull         不执行 git pull，适用于 CI 已检出指定提交的场景
  --dry-run         只显示将执行的命令，不构建或推送
  -h, --help        显示帮助

也可使用环境变量 IMAGE_NAME 和 GIT_REMOTE 设置默认值。
EOF
}

log() {
    printf '[publish] %s\n' "$*"
}

fail() {
    printf '[publish] 错误：%s\n' "$*" >&2
    exit 1
}

print_command() {
    printf '[publish] +'
    printf ' %q' "$@"
    printf '\n'
}

run() {
    print_command "$@"
    if (( ! DRY_RUN )); then
        "$@"
    fi
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "缺少命令：$1"
}

while (( $# > 0 )); do
    case "$1" in
        --image)
            (( $# >= 2 )) || fail "--image 缺少参数"
            IMAGE_NAME="$2"
            shift 2
            ;;
        --remote)
            (( $# >= 2 )) || fail "--remote 缺少参数"
            GIT_REMOTE="$2"
            shift 2
            ;;
        --no-pull)
            PULL_SOURCE=0
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "未知参数：$1"
            ;;
    esac
done

require_command git
require_command docker
[[ -n "$REPO_ROOT" ]] || fail "脚本必须在 Git 仓库中运行"
cd "$REPO_ROOT"

[[ -f pyproject.toml ]] || fail "未找到 pyproject.toml"
[[ -f Dockerfile ]] || fail "未找到 Dockerfile"
[[ "$IMAGE_NAME" =~ ^[a-zA-Z0-9._/-]+$ ]] || fail "镜像名称无效：$IMAGE_NAME"

git diff --quiet && git diff --cached --quiet || fail "工作区存在未提交修改，请先提交或暂存处理"
[[ -z "$(git status --porcelain --untracked-files=normal)" ]] || fail "工作区存在未跟踪文件，请先提交或删除"

git rev-parse --verify HEAD >/dev/null 2>&1 || fail "当前仓库没有可发布的提交"
branch="$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
[[ -n "$branch" ]] || fail "当前处于 detached HEAD，请切换到发布分支"
git remote get-url "$GIT_REMOTE" >/dev/null 2>&1 || fail "Git 远端不存在：$GIT_REMOTE"

docker info >/dev/null 2>&1 || fail "Docker daemon 不可用"

if (( PULL_SOURCE )); then
    log "拉取 $GIT_REMOTE/$branch 的最新代码"
    run git pull --ff-only "$GIT_REMOTE" "$branch"
fi

version="$(sed -n 's/^version[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' pyproject.toml | head -n 1)"
[[ -n "$version" ]] || fail "无法从 pyproject.toml 读取项目版本"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]] || fail "项目版本格式无效：$version"

version_image="${IMAGE_NAME}:${version}"
latest_image="${IMAGE_NAME}:latest"
commit="$(git rev-parse --short HEAD)"

log "提交：$commit"
log "版本：$version"
log "镜像：$version_image"
log "镜像：$latest_image"

run docker build --pull \
    --label "org.opencontainers.image.version=$version" \
    --label "org.opencontainers.image.revision=$(git rev-parse HEAD)" \
    -t "$version_image" \
    -t "$latest_image" \
    .

run docker push "$version_image"
run docker push "$latest_image"

if (( DRY_RUN )); then
    log "预演完成，未构建或推送镜像"
else
    log "发布完成：$version_image、$latest_image"
fi
