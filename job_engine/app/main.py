from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from app.admin.routes import router as admin_router
from app.api.partner import router as partner_router
from app.api.partner_assets import router as partner_assets_router
from app.api.routes import router as api_router
from app.ultron.routes import VIGIL_DIST, mount_vigil_static, router as ultron_router

app = FastAPI(title='Global Job WATCH TOWER', docs_url='/api/docs')
app.include_router(api_router)
app.include_router(partner_router)
app.include_router(partner_assets_router)
app.include_router(ultron_router)
# Legacy Jinja shell — recovery / debug only
app.include_router(admin_router, prefix='/legacy')

PANEL_REDIRECTS = {
    '/signals': 'signals',
    '/watchlist': 'watchlist',
    '/configs': 'searches',
    '/runs': 'activity',
    '/jobs': 'jobs',
    '/console': 'live',
    '/tower-health': 'health',
}


@app.get('/')
def vigil_root():
    index = VIGIL_DIST / 'index.html'
    if index.exists():
        return FileResponse(index)
    return JSONResponse({
        'error': 'VIGIL not built',
        'hint': 'cd job_engine/vigil && npm ci && npm run build',
        'legacy': '/legacy/',
    }, status_code=503)


def _register_panel_redirects() -> None:
    for path, panel in PANEL_REDIRECTS.items():

        async def _redir(panel_id: str = panel):
            return RedirectResponse(f'/?panel={panel_id}', status_code=307)

        app.add_api_route(
            path,
            _redir,
            methods=['GET'],
            name=f'redirect_{panel}',
        )


_register_panel_redirects()
mount_vigil_static(app)


@app.get('/favicon.svg')
def vigil_favicon():
    target = VIGIL_DIST / 'favicon.svg'
    if target.is_file():
        return FileResponse(target)
    return JSONResponse({'error': 'not found'}, status_code=404)


@app.get('/icons.svg')
def vigil_icons():
    target = VIGIL_DIST / 'icons.svg'
    if target.is_file():
        return FileResponse(target)
    return JSONResponse({'error': 'not found'}, status_code=404)


@app.get('/vigil/{resource_path:path}')
def vigil_public_files(resource_path: str):
    """Serve non-hashed public files from the VIGIL dist (favicon, models, etc.)."""
    target = (VIGIL_DIST / resource_path).resolve()
    if not str(target).startswith(str(VIGIL_DIST.resolve())):
        return JSONResponse({'error': 'forbidden'}, status_code=403)
    if target.is_file():
        return FileResponse(target)
    return JSONResponse({'error': 'not found'}, status_code=404)
