#!/usr/bin/env bash
set -euo pipefail
runtime_dir="$RUNNER_TEMP/assistant-runtime"
mkdir -p "$runtime_dir"
gh api repos/koreader/koreader/releases/latest > "$runtime_dir/koreader.json"
version=$(jq -r .tag_name "$runtime_dir/koreader.json")
url=$(jq -r '.assets[] | select(.name | endswith("_amd64.deb")) | .browser_download_url' "$runtime_dir/koreader.json")
test -n "$url"
curl --fail --location --retry 3 "$url" -o "$runtime_dir/koreader.deb"
sudo apt-get update -qq
sudo apt-get install -y "$runtime_dir/koreader.deb"
echo "KOREADER_VERSION=$version" >> "$GITHUB_ENV"
dpkg-query -W koreader
test -x /usr/lib/koreader/luajit

# Pin diagnostic behavior independently of the KOReader stable release.
gh release download 3.19.2 --repo LuaLS/lua-language-server \
  --pattern '*-linux-x64.tar.gz' --dir "$runtime_dir"
mkdir -p "$runtime_dir/luals"
tar -xzf "$runtime_dir/lua-language-server-3.19.2-linux-x64.tar.gz" -C "$runtime_dir/luals"
echo "$runtime_dir/luals/bin" >> "$GITHUB_PATH"
