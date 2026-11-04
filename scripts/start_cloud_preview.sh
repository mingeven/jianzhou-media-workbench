#!/usr/bin/env bash
set -euo pipefail

if [[ "${CODESPACES:-}" != "true" || -z "${CODESPACE_NAME:-}" ]]; then
    echo "此脚本仅用于 GitHub Codespaces。" >&2
    exit 1
fi

cd "$(dirname "$0")/.."
export JIANZHOU_DATA_DIR="$PWD/data/codespaces-web-demo"
export JIANZHOU_DEMO=1 JIANZHOU_PORT=8741 JIANZHOU_HOST=127.0.0.1
export JIANZHOU_NO_BROWSER=1 JIANZHOU_BUILD_PROFILE=codespaces JIANZHOU_WEB_MODE=1
export JIANZHOU_WEB_ORIGIN="https://${CODESPACE_NAME}-8741.app.github.dev"
unset JIANZHOU_TIKHUB_API_KEY JIANZHOU_LLM_API_KEY JIANZHOU_ASR_API_KEY
unset JIANZHOU_IMAGE_API_KEY JIANZHOU_WECHAT_APP_SECRET

mkdir -p "$JIANZHOU_DATA_DIR/logs"
nohup flock -n -F "$JIANZHOU_DATA_DIR/preview.lock" .venv/bin/python app.py \
    >> "$JIANZHOU_DATA_DIR/logs/preview.log" 2>&1 </dev/null &

for attempt in {1..30}; do
    if curl --fail --silent --max-time 1 http://127.0.0.1:8741/healthz >/dev/null; then
        echo "见舟预览已启动。请通过 Codespaces 的私有 8741 端口打开。"
        exit 0
    fi
    sleep 1
done

echo "预览未就绪，请查看 $JIANZHOU_DATA_DIR/logs/preview.log。" >&2
exit 1
