"""HTTP for MCP OAuth (services/mcp_oauth.py): discovery, client registration, the approval page and tokens."""
from __future__ import annotations

import html
import json
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from services.mcp_oauth import McpOAuth, OAuthError

AUTH_FIELDS = ("response_type", "client_id", "redirect_uri", "code_challenge", "code_challenge_method", "state", "scope", "resource")


async def _form(request: Request) -> dict[str, str]:
    raw = (await request.body()).decode("utf-8", "replace")
    if "json" in (request.headers.get("content-type") or ""):
        value = json.loads(raw or "{}")
        return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}
    return dict(parse_qsl(raw, keep_blank_values=True))


def _error(error: OAuthError) -> JSONResponse:
    return JSONResponse({"error": error.error, "error_description": str(error)}, status_code=error.status,
                        headers={"Cache-Control": "no-store"})


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
body{{font:16px system-ui,sans-serif;background:#111827;color:#f3f4f6;display:grid;place-items:center;min-height:100vh;margin:0}}
main{{max-width:28rem;padding:2rem;background:#1f2937;border-radius:1rem}}input,button{{font:inherit;width:100%;box-sizing:border-box;padding:.7rem;border-radius:.5rem;border:1px solid #4b5563;margin-top:.6rem}}
button{{background:#7c3aed;color:#fff;border:0;cursor:pointer}}small{{color:#9ca3af}}.error{{color:#fca5a5}}</style></head>
<body><main>{body}</main></body></html>""", status_code=status, headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"})


def create_mcp_oauth_router(oauth: McpOAuth) -> APIRouter:
    router = APIRouter()

    @router.get("/.well-known/oauth-protected-resource")
    @router.get("/.well-known/oauth-protected-resource/{path:path}")
    def protected_resource(request: Request, path: str = ""):
        return oauth.protected_resource(request, path)

    @router.get("/.well-known/oauth-authorization-server")
    @router.get("/.well-known/oauth-authorization-server/{path:path}")
    @router.get("/.well-known/openid-configuration")
    def authorization_server(request: Request, path: str = ""):
        return oauth.authorization_server(request)

    @router.post("/oauth/register")
    async def register(request: Request):
        try:
            body = json.loads((await request.body()) or b"{}")
            return JSONResponse(oauth.register(body if isinstance(body, dict) else {}), status_code=201,
                                headers={"Cache-Control": "no-store"})
        except (OAuthError, ValueError) as error:
            return _error(error if isinstance(error, OAuthError) else OAuthError("invalid_client_metadata", str(error)))

    def form_page(params: dict[str, str], message: str = "", status: int = 200) -> HTMLResponse:
        checked = oauth.check_request(params)
        hidden = "".join(f'<input type="hidden" name="{name}" value="{html.escape(params.get(name, ""))}">' for name in AUTH_FIELDS if params.get(name))
        scope = "las herramientas de Series Lab" if checked["profile"] == "series" else (
            "todas las herramientas MCP" if checked["profile"] == "all" else f"el perfil {checked['profile']}")
        error = f'<p class="error">{html.escape(message)}</p>' if message else ""
        return _page("Conectar con HocusPocus", f"""<h1>Conectar con HocusPocus</h1>
<p><b>{html.escape(checked['client']['name'])}</b> quiere usar {scope} de esta instalación.</p>
<p><small>Escribe la clave MCP de HocusPocus (Ajustes → Agentes externos). Solo se pide esta vez: el cliente recibe su propio token, que caduca y se renueva.</small></p>
{error}<form method="post" action="/oauth/authorize">{hidden}
<input type="password" name="key" autocomplete="off" placeholder="Clave MCP" required autofocus>
<button type="submit">Autorizar</button></form>""", status)

    @router.get("/oauth/authorize")
    def authorize_page(request: Request):
        params = {name: request.query_params.get(name, "") for name in AUTH_FIELDS}
        try:
            return form_page(params)
        except OAuthError as error:
            return _page("Autorización no válida", f"<h1>Autorización no válida</h1><p class=\"error\">{html.escape(str(error))}</p>", 400)

    @router.post("/oauth/authorize")
    async def authorize(request: Request):
        form = await _form(request)
        params = {name: form.get(name, "") for name in AUTH_FIELDS}
        try:
            return RedirectResponse(oauth.approve(params, form.get("key", "")), status_code=302)
        except OAuthError as error:
            if error.error in {"access_denied", "slow_down"}:
                try:
                    return form_page(params, str(error), error.status)
                except OAuthError:
                    pass
            return _page("Autorización no válida", f"<h1>Autorización no válida</h1><p class=\"error\">{html.escape(str(error))}</p>", error.status)

    @router.post("/oauth/token")
    async def token(request: Request):
        try:
            return JSONResponse(oauth.exchange(await _form(request)), headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
        except OAuthError as error:
            return _error(error)

    return router
