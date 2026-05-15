#!/usr/bin/env sh
set -eu

# Simple launcher that detects common runtimes and starts the app.
# Heroku performs build-step installs based on detected buildpacks (package.json, requirements.txt, etc.).

if [ -f package.json ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "Detected Node.js app — running npm start"
    exec npm start
  else
    echo "npm not found; cannot start Node app" >&2
    exit 1
  fi
elif [ -f requirements.txt ] || [ -f Pipfile ]; then
  if command -v python3 >/dev/null 2>&1; then
    if [ -f bot.py ]; then
      echo "Detected Python app — running bot.py"
      exec python3 bot.py
    else
      echo "Detected Python app but no bot.py found; set your entrypoint or add bot.py" >&2
      exit 1
    fi
  else
    echo "python3 not found; cannot start Python app" >&2
    exit 1
  fi
elif [ -f Procfile.dev ]; then
  echo "Found Procfile.dev — running via sh"
  exec sh -c "$(cat Procfile.dev | sed -n 's/^web:\s*//p')"
else
  echo "No recognized start target (package.json, requirements.txt, Pipfile, bot.py)." >&2
  echo "Add a start script (Node) or a bot.py (Python), or modify start.sh." >&2
  # Keep dyno alive so Heroku doesn't immediately exit when user deploys an app without a start command
  tail -f /dev/null
fi
