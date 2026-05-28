from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.db import create_tables, seed_municipalities_from_location_db


def create_app() -> FastAPI:
    app = FastAPI(title="Helio — Solar Opportunity Intelligence", version="2.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def startup():
        create_tables()
        seed_municipalities_from_location_db()

    from api.routers import municipalities, runs, chat, admin
    app.include_router(municipalities.router)
    app.include_router(runs.router)
    app.include_router(chat.router)
    app.include_router(admin.router)

    @app.get("/")
    def health():
        return {"status": "ok", "app": "Helio v2 — Solar Opportunity Intelligence"}

    return app


app = create_app()
