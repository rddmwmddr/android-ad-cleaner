#!/bin/zsh
# 把已发布的安装包传到百度网盘，生成分享链接，写进 index.html 的 REL（下载页「百度网盘」按钮），并自动提交推送
#   gui/upload_baidu.sh            版本取 gui/app.py 的 VERSION
#   gui/upload_baidu.sh 0.2.4
#   NO_PUSH=1 gui/upload_baidu.sh  只写 index.html，不提交推送
# 前提：GitHub Release 已公开；本机装了 BaiduPCS-Go 并已登录一次（在自己的终端里）：
#   BaiduPCS-Go login -bduss='…' -stoken='…'
# BDUSS / STOKEN 等于网盘账号登录凭证，不要写进脚本、仓库或聊天记录。
# 网盘目录沿用改名前的 /安卓去广告（已有分享链接指向它，#668）：/安卓去广告/v<版本>/<下载页里的 folder>/<安装包>；SHA256SUMS.txt、安装说明.txt 放在版本目录下。
# 每个文件一条分享链接；/安卓去广告 整个目录（全部版本）那条有就复用。
# 网盘里早期手动建的 /去广告/<平台>/ 也同步换成新版：旧安装包挪到不分享的 /去广告-旧版/，分享链接不变。
set -eo pipefail
cd "${0:A:h}/.."
PCS=${PCS:-$(command -v BaiduPCS-Go || echo ~/.local/bin/BaiduPCS-Go)}
GH=${GH:-$(command -v gh || echo ~/.local/bin/gh)}
VER=${1:-$(python3 -c "import re;print(re.search(r'VERSION = \"([^\"]+)\"', open('gui/app.py', encoding='utf-8').read()).group(1))")}
BASE="/安卓去广告"
ROOT="$BASE/v$VER"
LEGACY="/去广告"
ARCHIVE="/去广告-旧版"

[ -x "$PCS" ] || { echo "找不到 BaiduPCS-Go。安装：brew install baidupcs-go，或从 GitHub 发布页下载" >&2; exit 1; }
if "$PCS" who | grep -q "uid: 0,"; then
  echo "BaiduPCS-Go 还没登录。请在自己的终端运行：BaiduPCS-Go login -bduss='…' -stoken='…'" >&2; exit 1
fi

# 从 GitHub Release 下载，保证网盘里的文件和公开发布的是同一份
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
"$GH" release download "v$VER" -D "$STAGE" -p "AndroidAdCleaner-$VER-*" -p SHA256SUMS.txt
(cd "$STAGE" && shasum -a 256 -c SHA256SUMS.txt)

# 下载页里每个文件的 id / 网盘文件夹 / 文件名；顺便按下载页文字生成安装说明
ROWS=$(python3 gui/baidu_rows.py "$VER" "$STAGE/安装说明.txt")
[ -n "$ROWS" ] || { echo "index.html 里没有 $VER 的文件，先更新下载页" >&2; exit 1; }

code() { LC_ALL=C tr -dc 'a-z0-9' </dev/urandom | head -c 4; }
existing() {  # 已有的分享：打印「链接<TAB>提取码」；awk 读完全部输入，避免提前退出触发 pipefail
  "$PCS" share list | awk -v p="$1" '$6 == p && $3 ~ /pan\.baidu\.com/ && !found {print $3 "\t" $4; found = 1}'
}
share() {  # share <网盘路径> → 打印「链接<TAB>提取码」；同一路径有分享就沿用，重跑不重复建
  local found=$(existing "$1")
  [ -n "$found" ] && { print -r -- "$found"; return; }
  local c=$(code)
  local out=$("$PCS" share set -p "$c" --period 0 "$1")
  local url=$(print -r -- "$out" | grep -oE 'https://pan\.baidu\.com/s/[A-Za-z0-9_-]+' | head -1)
  [ -n "$url" ] || { echo "分享失败：$1\n$out" >&2; return 1; }
  print -r -- "$url	$c"
}

"$PCS" mkdir "$ROOT" >/dev/null 2>&1 || true
"$PCS" upload --policy overwrite "$STAGE/SHA256SUMS.txt" "$STAGE/安装说明.txt" "$ROOT"
LINKS=()
while IFS=$'\t' read -r id folder file; do
  "$PCS" mkdir "$ROOT/$folder" >/dev/null 2>&1 || true
  "$PCS" upload --policy overwrite "$STAGE/$file" "$ROOT/$folder"
  LINKS+=("$id	$(share "$ROOT/$folder/$file")")
done <<< "$ROWS"
LINKS+=("all	$(share "$BASE")")          # 下载页写的是「全部版本」；已有分享就沿用，链接不变

# 早期的 /去广告/<平台>/ 分享（浏览量高）换成这一版
if "$PCS" ls "$LEGACY" >/dev/null 2>&1; then
  mkdir -p "$STAGE/legacy"
  python3 gui/baidu_rows.py --legacy "$VER" "$STAGE/legacy" "$STAGE/SHA256SUMS.txt" >/dev/null
  "$PCS" upload --policy overwrite "$STAGE/legacy/先看我-选哪个文件夹.txt" "$LEGACY"
  while IFS=$'\t' read -r id folder file; do
    "$PCS" ls "$LEGACY/$folder" >/dev/null 2>&1 || "$PCS" mkdir "$LEGACY/$folder" >/dev/null
    for old in $("$PCS" ls "$LEGACY/$folder" | grep -oE 'AndroidAdCleaner-[0-9.]+-[a-z0-9-]+\.(dmg|exe|zip|apk)' | grep -vF -- "-$VER-" | sort -u); do
      "$PCS" mkdir "$ARCHIVE/$folder" >/dev/null 2>&1 || true
      "$PCS" mv "$LEGACY/$folder/$old" "$ARCHIVE/$folder"
    done
    "$PCS" upload --policy overwrite "$STAGE/$file" "$STAGE/legacy/$folder/安装说明.txt" "$STAGE/legacy/$folder/SHA256校验.txt" "$LEGACY/$folder"
  done <<< "$ROWS"
fi

printf '%s\n' "${LINKS[@]}" | python3 gui/baidu_rows.py --write

if [ -n "$NO_PUSH" ]; then
  echo "已写入 index.html（未推送）。"
elif ! git diff --quiet -- index.html; then
  git add index.html
  git commit -q -m "docs: Baidu Netdisk links for $VER"
  git push -q origin HEAD
  echo "已提交并推送 index.html，下载页的「百度网盘」按钮几分钟后生效（GitHub Pages 重新部署）。"
fi
