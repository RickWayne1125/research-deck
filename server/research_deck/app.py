"""The FastAPI app: core routes, each panel's package (research_deck.<pkg>.api:router), and the built web app."""
from __future__ import annotations

import asyncio
import importlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__, actors, config, events, projects, system

log = logging.getLogger("research_deck")

# Each package owns its routes in <pkg>/api.py and exports `router`.
PANEL_PACKAGES = ("dag", "agents", "writing", "coding", "experiments", "viz")
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    events.hub.bind_loop(asyncio.get_running_loop())
    yield
    try:
        from .agents import runner
        runner.stop_all()
    except Exception:  # noqa: BLE001 — shutdown must not fail on a missing package
        pass


def is_tailnet_request(request: Request) -> bool:
    host = (request.headers.get("host") or "").split(":")[0].rstrip(".").lower()
    return bool(config.TAILNET_HOST and host == config.TAILNET_HOST.lower()) or any(
        k.lower().startswith("tailscale-") for k in request.headers) or "x-forwarded-for" in request.headers


def create_app() -> FastAPI:
    app = FastAPI(title="Research Deck", version=__version__, lifespan=lifespan)

    @app.middleware("http")
    async def tailnet_owner_only(request: Request, call_next):
        # Requests that come through Tailscale Serve (the tailnet host, or Serve's identity/forwarding headers) must
        # be from one of the configured owners; anything else on the tailnet is refused, the whole site included.
        if is_tailnet_request(request):
            login = (request.headers.get("tailscale-user-login") or "").lower()
            if not login or login not in config.TAILNET_OWNERS:
                return JSONResponse({"detail": "this tailnet identity may not use this dashboard"}, status_code=403)
        return await call_next(request)

    @app.middleware("http")
    async def same_origin_only(request: Request, call_next):
        # The server listens on loopback only; a page from another origin must not drive the agents, write files or
        # read them. Mutations need an allowed Origin (when the browser sends one) and the X-RD-Request header, which a
        # cross-origin page cannot set without a preflight; reads flagged cross-site by the browser are refused.
        if request.url.path.startswith("/api/"):
            if request.method in MUTATING:
                origin = request.headers.get("origin")
                if origin and origin not in config.ALLOWED_ORIGINS:
                    return JSONResponse({"detail": f"origin not allowed: {origin}"}, status_code=403)
                if request.headers.get(config.REQUEST_HEADER) != "1":
                    return JSONResponse({"detail": "missing X-RD-Request header"}, status_code=403)
            elif request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "cross-site request refused"}, status_code=403)
        return await call_next(request)

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.ALLOWED_HOSTS)

    app.include_router(events.router)
    app.include_router(actors.router)
    app.include_router(system.router)
    app.include_router(projects.router)
    for pkg in PANEL_PACKAGES:
        try:
            module = importlib.import_module(f".{pkg}.api", __package__)
        except ModuleNotFoundError as e:
            log.warning("panel package %s not available: %s", pkg, e)
            continue
        app.include_router(module.router)

    if config.WEB_DIST.exists():
        app.mount("/assets", StaticFiles(directory=config.WEB_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "not found"}, status_code=404)
            target = (config.WEB_DIST / path).resolve()
            if path and target.is_file() and config.WEB_DIST.resolve() in target.parents:
                return FileResponse(target)
            return FileResponse(config.WEB_DIST / "index.html")

    return app


app = create_app()
