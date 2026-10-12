# LAN authentication

Loopback stays open. When the process is reachable beyond loopback, remote
`/api/` and `/classic` requests need the LAN token. Sharing used to be
credential-free unless `LOREFRAME_LAN_AUTH` was set; any device on the Wi-Fi
could read stored API keys and change settings. Auth is now **on by default**
whenever the app is shared. Set `LOREFRAME_LAN_AUTH=0` to opt out knowingly.

Code: `app/services/lan_auth.py`, `app/routers/lan_auth.py`,
`ui/src/components/LanAuthGate.tsx`. Tests: `tests/test_lan_auth.py`,
`tests/test_security_local.py`.

Related: [MCP connect](SCENE_EFFECTS_AND_MCP.md#enable-and-connect-mcp)
(MCP uses its own bearer; LAN auth does not wrap `/api/v1/mcp`).

## When it is on

`lan_share_enabled` is true when `PINOKIO_SHARE_LOCAL` is true, or when
`SERVER_NAME` is set and is not a loopback / `localhost` host. `lan_auth_enabled`
then follows `LOREFRAME_LAN_AUTH`:

| `LOREFRAME_LAN_AUTH` | Shared beyond loopback | Auth |
|---|---|---|
| unset | yes | **on** |
| `1` / `true` / `yes` / `on` | yes | on |
| `0` / `false` / `no` / `off` | yes | off (opt-out) |
| any | no (loopback only) | off — nothing to protect |

`remote_lan_auth_required` is the gate used by the middleware: sharing on, auth
on, and the peer is not a real loopback client talking to a loopback `Host`.
A remote peer cannot bypass the gate by sending `Host: localhost`. Numeric
`<port>.localhost` proxy hosts are not exempt while sharing.

## Token and cookie

- `LOREFRAME_LAN_TOKEN` must be at least 24 characters. If unset, the process
  mints one `secrets.token_urlsafe(32)` token and prints it once at startup:
  `[LAN Auth] Enter this session token in the LAN browser`. Set the env var
  to keep the same token across restarts.
- Login: `POST /api/v1/auth/lan/login` with `{"token": "…"}`. Success sets the
  HttpOnly cookie `loreframe_lan_session` (HMAC of the token, not the raw
  bearer). Max age is 30 days (`LAN_SESSION_MAX_AGE`).
- Status: `GET /api/v1/auth/lan/status` → `{enabled, sharing, required, authenticated}`.
  Logout: `POST /api/v1/auth/lan/logout` clears the cookie.
- API clients may send `Authorization: Bearer <token>` instead of the cookie.
- Failed guesses: 8 per peer per 60 s, then HTTP `429` with `Retry-After`.

The React gate (`LanAuthGate`) wraps the app: it calls status, and if
`required && !authenticated` it shows the unlock form. HTTP (not HTTPS) shows
the in-app warning; `SameSite=Strict` still works on a same-origin LAN URL.

## What is not gated

These paths never require the LAN token:

- `/api/v1/auth/lan/login`, `/api/v1/auth/lan/status`
- `/api/v1/mcp`, `/api/v1/mcp/…`, `/api/v1/wangp/mcp` — MCP has its own
  `HOCUS_MCP_TOKEN` / Settings key. A second LAN bearer here would make
  external MCP clients impossible.

Static UI assets are not under `/api/` or `/classic`, so they load; the API
and classic UI do not.

## Operator workflow

1. Bind the server for LAN (`PINOKIO_SHARE_LOCAL=1` or a non-loopback
   `SERVER_NAME`). Restart.
2. Read the startup lines. If you did not set `LOREFRAME_LAN_TOKEN`, copy the
   printed session token.
3. On the phone or another machine, open `http://<host>:<port>/`. Enter the
   token once. The cookie lasts 30 days on that browser.
4. For a stable token, set `LOREFRAME_LAN_TOKEN` (24+ characters) and restart.

## Pitfalls

- **“Optional auth” is stale.** README and the August 2026 audit said
  `LOREFRAME_LAN_AUTH=true` was opt-in and QR/LAN was free. The default flipped:
  sharing turns the gate on; `LOREFRAME_LAN_AUTH=0` is the opt-out.
- **Loopback stays free.** `http://127.0.0.1:<port>/` on the same machine does
  not ask for the token.
- **MCP is a different key.** A valid LAN cookie does not authorize
  `/api/v1/mcp`. A valid MCP bearer does not unlock `/api/v1/outputs`.
- **Token in the log is one process.** A restart without `LOREFRAME_LAN_TOKEN`
  mints a new token; old cookies fail until you log in again.
- **Spoofed `Host` does not count as local.** Only a loopback peer addressing
  a loopback host is exempt. `X-Forwarded-For` / `X-Real-IP` that are not
  loopback keep the request remote.
- **`LOREFRAME_LAN_TOKEN` shorter than 24 characters crashes startup**
  (`ValueError`).
