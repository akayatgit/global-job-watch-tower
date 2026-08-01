# VIGIL — Watch Tower air ops shell

Face name **VIGIL**. Backend brain **ultron** (`/ws/ultron`, `/api/ultron/*`).

## Dev

```bash
export PATH="/home/user/actions-runner/externals/node20/bin:$PATH"
npm install
npm run dev   # proxies API to :8001
```

## Production

`job_engine/restart_app.sh` runs `npm run build` and FastAPI serves `dist/` at `/`.
Legacy Jinja: `/legacy/`.
