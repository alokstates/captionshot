#!/usr/bin/env bash
# CaptionShot installer for macOS. Python is not needed.
#   curl -fsSL https://raw.githubusercontent.com/alokstates/captionshot/main/install.sh | bash
#
# Everything is inside main(), which runs on the last line, so a download cut off
# halfway cannot run a partial script.
set -euo pipefail

main() {
  local base="https://github.com/alokstates/captionshot/releases/latest/download"

  [ "$(uname -s)" = "Darwin" ] || { echo "This installer is for macOS. On Windows, see the README." >&2; exit 1; }

  # Ask the hardware: a Terminal running under Rosetta reports x86_64 from uname on Apple silicon.
  local arch="x86_64"
  [ "$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" = "1" ] && arch="arm64"
  local zip="CaptionShot-macOS-$arch.zip"

  # Not "local": the EXIT trap runs after main() has returned.
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT

  echo "Downloading CaptionShot ($arch)..."
  curl -fsSL --retry 3 -o "$tmp/$zip" "$base/$zip"
  curl -fsSL --retry 3 -o "$tmp/SHA256SUMS.txt" "$base/SHA256SUMS.txt"

  echo "Verifying the download..."
  local want got
  want="$(awk -v f="$zip" '$2 == f || $2 == "*" f { print $1 }' "$tmp/SHA256SUMS.txt")"
  got="$(shasum -a 256 "$tmp/$zip" | awk '{ print $1 }')"
  if [ -z "$want" ] || [ "$want" != "$got" ]; then
    echo "Checksum mismatch for $zip. Nothing was installed." >&2
    exit 1
  fi

  ditto -x -k "$tmp/$zip" "$tmp/unpacked"

  # /Applications is writable for admin users without sudo; otherwise use the personal folder.
  local dest="/Applications"
  if [ ! -w "$dest" ]; then
    dest="$HOME/Applications"
    mkdir -p "$dest"
  fi

  pkill -x CaptionShot 2>/dev/null || true
  rm -rf "$dest/CaptionShot.app"
  ditto "$tmp/unpacked/CaptionShot.app" "$dest/CaptionShot.app"

  open "$dest/CaptionShot.app"

  cat <<EOF

CaptionShot is installed in $dest and is running in your menu bar.

  Take a screenshot:  Cmd+Shift+2
  First use:          macOS asks for Screen Recording permission. Turn on CaptionShot in
                      System Settings > Privacy & Security > Screen & System Audio Recording,
                      then quit and reopen CaptionShot.

EOF
}

main "$@"
