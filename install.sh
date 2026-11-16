#!/usr/bin/env sh
# Install the standalone EnvContract script into ~/.local/bin.
set -eu

repo_raw="https://raw.githubusercontent.com/ice-wocker/envcontract/main/envcontract.py"
install_dir="${HOME}/.local/bin"
target="${install_dir}/envcontract"
mkdir -p "$install_dir"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$repo_raw" -o "$target"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "$target" "$repo_raw"
else
  echo "EnvContract installer requires curl or wget." >&2
  exit 1
fi
chmod +x "$target"
printf 'EnvContract installed at %s\n' "$target"
case ":${PATH}:" in
  *":${install_dir}:"*) ;;
  *) printf 'Add it to PATH: export PATH="$HOME/.local/bin:$PATH"\n' ;;
esac
