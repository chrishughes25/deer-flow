#!/bin/bash
set -e

# ── Generate config.yaml from environment variables ─────────────────────────
# DeerFlow's config.yaml natively supports $ENV_VAR references, so we just
# need to write a config file that points to the right model + tools.

CONFIG_PATH="${DEER_FLOW_CONFIG_PATH:-/app/backend/config.yaml}"

# If no config.yaml exists, generate one from env vars.
# DEERFLOW_MODEL controls which LLM provider to use.
if [ ! -f "$CONFIG_PATH" ]; then
  MODEL="${DEERFLOW_MODEL:-deepseek-v3}"

  case "$MODEL" in
    gpt-4o|gpt-4o-mini|gpt-*)
      cat > "$CONFIG_PATH" <<YAML
config_version: 5
models:
- name: ${MODEL}
  display_name: ${MODEL}
  use: langchain_openai:ChatOpenAI
  model: ${MODEL}
  api_key: \$OPENAI_API_KEY
  max_tokens: 8192
  supports_vision: true
YAML
      ;;
    claude-*)
      cat > "$CONFIG_PATH" <<YAML
config_version: 5
models:
- name: ${MODEL}
  display_name: ${MODEL}
  use: deerflow.models.claude_provider:ChatAnthropicWithThinking
  model: ${MODEL}
  api_key: \$ANTHROPIC_API_KEY
  max_tokens: 8192
  supports_vision: true
YAML
      ;;
    deepseek-*)
      cat > "$CONFIG_PATH" <<YAML
config_version: 5
models:
- name: ${MODEL}
  display_name: ${MODEL}
  use: deerflow.models.patched_deepseek:PatchedChatDeepSeek
  model: deepseek-chat
  api_key: \$DEEPSEEK_API_KEY
  max_tokens: 8192
  supports_vision: false
YAML
      ;;
    *)
      echo "Unknown DEERFLOW_MODEL: $MODEL — using config.template.yaml"
      cp /app/config.template.yaml "$CONFIG_PATH"
      ;;
  esac

  # Append shared config sections (tools, sandbox, etc.)
  cat >> "$CONFIG_PATH" <<YAML
tool_groups:
- name: web
tools:
- name: web_search
  group: web
  use: deerflow.community.tavily.tools:web_search_tool
  max_results: 8
tool_search:
  enabled: false
sandbox:
  # Research reports must be returned INLINE as the agent's final message — the
  # agent has no need to run shell or write files. Host bash is the write surface
  # that let a run create /mnt/user-data/outputs/*.md and "present" it instead of
  # returning the report; keep it off.
  use: deerflow.sandbox.local:LocalSandboxProvider
  allow_host_bash: false
  bash_output_max_chars: 20000
  read_file_output_max_chars: 50000
skills:
  container_path: /app/skills
title:
  enabled: true
  max_words: 6
  max_chars: 60
summarization:
  enabled: true
  trigger:
  - type: tokens
    value: 15564
  keep:
    type: messages
    value: 10
memory:
  enabled: false
checkpointer:
  type: sqlite
  connection_string: checkpoints.db
log_level: ${DEERFLOW_LOG_LEVEL:-info}
token_usage:
  enabled: ${DEERFLOW_TOKEN_USAGE:-false}
uploads:
  pdf_converter: auto
YAML

  echo "Generated config.yaml for model: $MODEL"
fi

export DEER_FLOW_CONFIG_PATH="$CONFIG_PATH"
export DEER_FLOW_HOME="${DEER_FLOW_HOME:-/app/backend/.deer-flow}"
mkdir -p "$DEER_FLOW_HOME"

# ── Start langgraph in background ───────────────────────────────────────────
echo "Starting langgraph server on :2024..."
cd /app/backend
uv run langgraph dev \
  --no-browser --allow-blocking --no-reload \
  --host 0.0.0.0 --port 2024 --n-jobs-per-worker 10 &
LANGGRAPH_PID=$!

# Wait for langgraph to be ready
for i in $(seq 1 30); do
  if curl -sf http://localhost:2024/ok > /dev/null 2>&1; then
    echo "langgraph ready"
    break
  fi
  sleep 2
done

# ── Start gateway (foreground — Railway monitors this process) ──────────────
echo "Starting gateway on :${PORT:-8001}..."
export DEER_FLOW_CHANNELS_LANGGRAPH_URL="http://localhost:2024"
export DEER_FLOW_CHANNELS_GATEWAY_URL="http://localhost:${PORT:-8001}"

exec uv run uvicorn app.gateway.app:app \
  --host 0.0.0.0 \
  --port "${PORT:-8001}" \
  --workers 2
