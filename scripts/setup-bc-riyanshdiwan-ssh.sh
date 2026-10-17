#!/usr/bin/env bash
# One-shot laptop setup: cloudflared + SSH config for bc-riyanshdiwan
# Binary-only install (no Homebrew/apt/winget). Safe to re-run.
set -euo pipefail

OS="$(uname -s)"
ARCH="$(uname -m)"
HOME_BIN="${HOME}/bin"
SSH_DIR="${HOME}/.ssh"
SSH_CONFIG="${SSH_DIR}/config"
HOST_BLOCK='Host bc-riyanshdiwan
  HostName bc-pool-262.thecosmoslabs.com
  User riyanshdiwan
  IdentityFile ~/.ssh/id_ed25519_cursor
  ProxyCommand "$HOME/bin/cloudflared" access ssh --hostname %h'

mkdir -p "$HOME_BIN" "$SSH_DIR"
chmod 700 "$SSH_DIR"

install_cloudflared() {
  if [[ -x "${HOME_BIN}/cloudflared" ]]; then
    echo "Keeping existing ${HOME_BIN}/cloudflared"
    return 0
  fi
  case "$OS" in
    Darwin)
      case "$ARCH" in
        arm64) URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz" ;;
        x86_64) URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz" ;;
        *) echo "Unsupported Mac arch: $ARCH" >&2; exit 1 ;;
      esac
      curl -fsSL -o /tmp/cloudflared.tgz "$URL"
      tar -xzf /tmp/cloudflared.tgz -C "$HOME_BIN" cloudflared
      chmod +x "${HOME_BIN}/cloudflared"
      xattr -d com.apple.quarantine "${HOME_BIN}/cloudflared" 2>/dev/null || true
      ;;
    Linux)
      curl -fsSL -o "${HOME_BIN}/cloudflared" \
        "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
      chmod +x "${HOME_BIN}/cloudflared"
      ;;
    *)
      echo "Run this script on macOS or Linux. On Windows Intel, use PowerShell steps from the portal." >&2
      exit 1
      ;;
  esac
}

write_ssh_config() {
  local tmp marker_start marker_end
  marker_start="# BEGIN bc-riyanshdiwan (cursor setup)"
  marker_end="# END bc-riyanshdiwan"
  tmp="$(mktemp)"
  if [[ -f "$SSH_CONFIG" ]]; then
    awk -v start="$marker_start" -v end="$marker_end" '
      $0 == start { skip=1; next }
      $0 == end { skip=0; next }
      !skip && !/^Host bc-riyanshdiwan$/ { print }
    ' "$SSH_CONFIG" > "$tmp" || true
    # Also drop legacy block without markers
    awk '
      /^Host bc-riyanshdiwan$/ { skip=1; next }
      skip && /^Host / { skip=0 }
      skip && /^Host bc-riyanshdiwan$/ { next }
      skip { next }
      { print }
    ' "$tmp" > "${tmp}.2" && mv "${tmp}.2" "$tmp"
  fi
  {
    cat "$tmp" 2>/dev/null || true
    echo "$marker_start"
    echo "$HOST_BLOCK"
    echo "$marker_end"
  } > "$SSH_CONFIG"
  chmod 600 "$SSH_CONFIG"
  rm -f "$tmp"
}

install_cloudflared
write_ssh_config

echo ""
echo "Installed: ${HOME_BIN}/cloudflared"
"${HOME_BIN}/cloudflared" --version
echo ""
echo "SSH config updated: ${SSH_CONFIG}"
echo ""
echo "Next (on THIS laptop): ssh bc-riyanshdiwan"
echo "Complete the Cloudflare browser login when prompted."
