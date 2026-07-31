from fastapi import FastAPI

from app.admin.routes import router as admin_router
from app.api.routes import router as api_router

app = FastAPI(title='Global Job WATCH TOWER', docs_url='/api/docs')
app.include_router(api_router)
app.include_router(admin_router)
