#!/bin/zsh
# Initial setup for video-use-test on a new machine.
# Idempotent — safe to re-run.
#
# What it does:
#  1. Verifies prereqs (Python 3.10+, ffmpeg)
#  2. Installs Python deps (video-use editable + google-api libs)
#  3. Creates video-use/.env from .env.example if missing
#  4. Creates publishing/{tokens,credentials,publishing-state,scripts/logs} dirs
#  5. Symlinks external_skills/* into ~/.claude/skills/ for Claude Code use
#  6. (Optional) Registers launchd post-monitor schedule
#
# What it does NOT do (you must do these manually — see SETUP.md):
#  • Set ELEVENLABS_API_KEY in video-use/.env
#  • Place YouTube OAuth client_secret.json in publishing/credentials/
#  • Run the OAuth authorize flow per channel
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
echo "📁 Project root: $ROOT"
echo ""

# ---- 1. Prereqs ----
echo "🔍 Checking prereqs..."
command -v python3 >/dev/null || { echo "❌ python3 not found. Install Python 3.10+." >&2; exit 1; }
PYV=$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
echo "   python3: $(command -v python3) ($PYV)"

command -v ffmpeg >/dev/null || { echo "❌ ffmpeg not found. Install: brew install ffmpeg" >&2; exit 1; }
echo "   ffmpeg:  $(command -v ffmpeg)"

# ---- 2. Python deps ----
echo ""
echo "📦 Installing Python deps..."
python3 -m pip install --quiet --upgrade pip
python3 -m pip install --quiet -e "$ROOT/video-use"
python3 -m pip install --quiet google-auth google-auth-oauthlib google-api-python-client requests pyyaml
echo "   ✅ Python deps installed"

# ---- 3. .env ----
echo ""
ENV_FILE="$ROOT/video-use/.env"
if [[ -f "$ENV_FILE" ]]; then
  echo "🔐 .env exists at $ENV_FILE (not overwriting)"
else
  cp "$ROOT/video-use/.env.example" "$ENV_FILE"
  echo "🔐 Created $ENV_FILE — edit it to add your ELEVENLABS_API_KEY"
fi

# ---- 4. Required dirs ----
mkdir -p "$ROOT/publishing/tokens/youtube" \
         "$ROOT/publishing/credentials" \
         "$ROOT/publishing/publishing-state/source-podcast" \
         "$ROOT/publishing/scripts/logs" \
         "$ROOT/publishing/audio/bgm" \
         "$ROOT/publishing/audio/sfx" \
         "$ROOT/source-podcast/edit/transcripts" \
         "$ROOT/source-podcast/edit/shorts_v2"

# ---- 5. Skill symlinks ----
echo ""
echo "🔗 Symlinking external_skills/ into ~/.claude/skills/..."
mkdir -p "$HOME/.claude/skills"
for skill in post-monitor youtube-uploader; do
  src="$ROOT/external_skills/$skill"
  dst="$HOME/.claude/skills/$skill"
  if [[ -L "$dst" || -e "$dst" ]]; then
    echo "   $skill: target already exists at $dst (skipped)"
  else
    ln -s "$src" "$dst"
    echo "   $skill: linked → $src"
  fi
done

# ---- 6. launchd (optional) ----
echo ""
read "yn?Register daily post-monitor at 08:00 (launchd)? [y/N] "
if [[ "$yn" == "y" || "$yn" == "Y" ]]; then
  bash "$ROOT/publishing/scripts/install_launchd.sh"
else
  echo "   Skipped. Run later: bash publishing/scripts/install_launchd.sh"
fi

# ---- Done ----
echo ""
echo "✅ Base setup complete."
echo ""
echo "Next steps (see SETUP.md for details):"
echo "  1. Add ELEVENLABS_API_KEY to $ENV_FILE"
echo "  2. Create your Google Cloud OAuth project, enable YouTube Data + Analytics APIs"
echo "  3. Place client_secret.json at $ROOT/publishing/credentials/youtube_client_secret.json"
echo "  4. Authorize each YouTube channel:"
echo "     python3 external_skills/youtube-uploader/scripts/upload.py --authorize \\"
echo "       --token publishing/tokens/youtube/<account_id>.json"
echo "  5. Try a dry-run of post-monitor:"
echo "     python3 publishing/scripts/monitor_runner.py --force --dry-run"
