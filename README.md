# Netflix-Tv-Bot

## **Heroku**

This repository now includes minimal files to enable Heroku deployments:

- `Procfile` — starts the app via `start.sh`.
- `start.sh` — simple launcher that auto-detects Node.js or Python entrypoints.
- `app.json` — metadata for the Heroku Button / app manifest.

How it works:

- Heroku will detect the project language during build if you include `package.json` (Node) or `requirements.txt` / `Pipfile` (Python).
- The `Procfile` runs `sh start.sh` which attempts to run `npm start` for Node projects or `python3 bot.py` for Python projects. Adjust `start.sh` or add a proper start script/entrypoint for your app.

Quick deploy (Heroku CLI):

1. Create a Heroku app: `heroku create`
2. Push your repo: `git push heroku main`
3. Check logs: `heroku logs --tail`

Alternatively, use the `app.json` with the Heroku Button in the Heroku dashboard to deploy from this repository.

If you want me to wire this specifically for Node or Python (add `Procfile` entry, `runtime.txt`, `requirements.txt`, `package.json` or a `Dockerfile`), tell me which language and I'll scaffold the exact files.

### Python

I added a minimal Python scaffold: `requirements.txt`, `runtime.txt`, and `bot.py`.

- `bot.py` is a tiny Flask app (with a fallback HTTP server so local checks work without installing Flask).
- `requirements.txt` contains `Flask` and `gunicorn`; Heroku will install these during build.
- `Procfile` is configured to run `gunicorn bot:app`.

Deploy steps (Python):

```bash
git add .
git commit -m "Add Heroku Python support"
heroku create
git push heroku main
heroku logs --tail
```

If your original Python bot has a different entrypoint (not `bot.py`) tell me its filename and I'll update `Procfile` and `start.sh` accordingly.

