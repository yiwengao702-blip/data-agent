#!/usr/bin/env bash
# =============================================================================
# 下载 bge-large-zh-v1.5 嵌入模型权重到本目录
#
# 背景：模型权重（pytorch_model.bin，约 1.3GB）已移出版本控制，不入库，
#       仅作本地 / 容器挂载使用。本脚本用于首次部署前拉取权重，使
#       docker/docker-compose.yaml 中的 embedding 服务（HF TEI）能正常加载。
#
# 用法：
#   bash docker/embedding/download_model.sh
#
# 网络：默认从 HuggingFace 官方 CDN 下载；国内环境可设镜像加速：
#   export HF_ENDPOINT=https://hf-mirror.com
#   （或 https://mirror.ghproxy.com/https://huggingface.co）
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="$SCRIPT_DIR/bge-large-zh-v1.5"
REPO="BAAI/bge-large-zh-v1.5"

mkdir -p "$TARGET_DIR"
cd "$TARGET_DIR"

# 已存在权重则跳过
if [ -f pytorch_model.bin ] || [ -f model.safetensors ]; then
  echo "[download_model] 检测到已有模型权重（$(pwd)），跳过下载。"
  exit 0
fi

HF_ENDPOINT="${HF_ENDPOINT:-https://huggingface.co}"

# 方式一：huggingface-cli（推荐，完整拉取并校验）
if command -v huggingface-cli >/dev/null 2>&1; then
  echo "[download_model] 使用 huggingface-cli 下载 $REPO ..."
  huggingface-cli download "$REPO" --local-dir . --local-dir-use-symlinks False
  echo "[download_model] 下载完成：$(pwd)"
  exit 0
fi

# 方式二：curl 直连（仅拉取运行必需的权重 + 配置；配置若已存在则跳过）
echo "[download_model] 未检测到 huggingface-cli，改用 curl 从 $HF_ENDPOINT 下载 ..."
FILES=(
  "pytorch_model.bin"
  "config.json"
  "tokenizer.json"
  "tokenizer_config.json"
  "vocab.txt"
  "special_tokens_map.json"
  "modules.json"
  "sentence_bert_config.json"
  "config_sentence_transformers.json"
  "1_Pooling/config.json"
  "README.md"
)
for f in "${FILES[@]}"; do
  if [ -f "$f" ]; then
    echo "  -> 已存在，跳过 $f"
    continue
  fi
  url="$HF_ENDPOINT/$REPO/resolve/main/$f"
  echo "  -> $f"
  mkdir -p "$(dirname "$f")"
  if ! curl -fL -o "$f" "$url"; then
    echo "[download_model] 下载 $f 失败：请检查网络，或设置 HF_ENDPOINT 镜像后重试。" >&2
    exit 1
  fi
done
echo "[download_model] 下载完成：$(pwd)"
echo "[download_model] 提示：安装后可用『huggingface-cli download $REPO』做带校验的完整拉取。"
