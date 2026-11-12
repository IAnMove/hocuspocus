"""Shared process entry for the full server and the core server.

Both roots call ``run``. Host choice, the bind-before-announce fall-forward,
the startup banner and ``settings/server-endpoint.json`` live here. Profile
prints, the quiet-access filter and resume-on-startup stay with the caller
and are passed in: ``lan_messages`` is printed as given, and ``prepare`` runs
after the banner with the display host and the port that was actually bound.
The banner lines are what Pinokio's launcher regex captures; keep them
byte-for-byte the same as the full server's historical announcement.
"""

import os
import sys


def run(api, *, ui_ready, endpoint_path, prepare, lan_messages):
    """Bind a port, announce the URLs, then serve ``api`` on that socket."""
    port = int(os.environ.get("SERVER_PORT", "7860"))

    # Bind-host resolution priority:
    #   1. PINOKIO_SHARE_LOCAL — Pinokio's per-app + global ENVIRONMENT
    #      var. "true" → 0.0.0.0 (LAN-accessible), anything else
    #      → 127.0.0.1 (loopback only). This is the primary Pinokio path
    #      and CRITICALLY: per-app ENVIRONMENT overrides global here
    #      because os.environ reflects the merged shell env. (start.js's
    #      kernel.envs only sees global, which is why we can't make this
    #      decision in start.js — Pinokio doesn't merge per-app into
    #      kernel.envs as of 2026-05-04.)
    #   2. SERVER_NAME — manual override for direct python launches
    #      outside Pinokio. Lets devs force a bind without going through
    #      the env-var dance.
    #   3. Default 127.0.0.1 (safe loopback).
    pinokio_share = (os.environ.get("PINOKIO_SHARE_LOCAL") or "").strip().lower()
    if pinokio_share == "true":
        host = "0.0.0.0"
    elif pinokio_share == "false":
        host = "127.0.0.1"
    else:
        host = os.environ.get("SERVER_NAME", "127.0.0.1")

    for _lan_auth_message in lan_messages:
        print(_lan_auth_message)

    # Port resolution: Pinokio hands us a free port via SERVER_PORT, but a
    # stale prior instance or another app can still be holding it by the time
    # we bind. Bind now (falling forward to the next free port) and hand the
    # socket to Uvicorn: the URL printed below is then already ours, so the
    # LAN proxy Pinokio starts on reading it cannot take the port first.
    from services.server_lifecycle import bind_listener
    try:
        listener, resolved_port = bind_listener(host, port)
    except OSError:
        print(
            f"\n[HocusPocus Lab] ERROR: could not find a free port in "
            f"{port}-{port + 20}. Another app (or a stale HocusPocus Lab instance) "
            f"is holding them.\n"
            f"  • Close the other program, or stop the existing HocusPocus Lab from "
            f"the Pinokio menu, then Start again.\n"
            f"  • On Windows you can see what holds a port with: "
            f"netstat -ano | findstr :{port}\n",
            flush=True,
        )
        sys.exit(1)
    if resolved_port != port:
        print(
            f"[HocusPocus Lab] Port {port} was busy — using {resolved_port} instead.",
            flush=True,
        )
        port = resolved_port

    # Browsers can't navigate to 0.0.0.0 (it's a non-routable bind
    # address), so when binding wider we still SURFACE the loopback
    # URL — that's what Pinokio's regex captures from this output and
    # hands to its built-in browser. The actual bind stays 0.0.0.0 so
    # LAN access works; only the displayed URL is loopback.
    display_host = "127.0.0.1" if host == "0.0.0.0" else host

    print(f"\n{'='*50}")
    print(f"  {'HocusPocus Lab UI:' if ui_ready else 'Web UI repair page (API only):'} http://{display_host}:{port}/")
    # Trailing slash required: the Gradio submount 404s the bare path.
    print(f"  Classic UI:    http://{display_host}:{port}/classic/")
    print(f"  API docs:      http://{display_host}:{port}/docs")
    if host == "0.0.0.0":
        print(f"  (Bound to {host} — LAN-accessible via this machine's IP)")
    print(f"{'='*50}\n")
    try:
        from services.server_endpoint import publish_server_endpoint
        publish_server_endpoint(
            endpoint_path,
            host=host, display_host=display_host, port=port,
        )
    except OSError as error:
        print(f"[HocusPocus Lab] Could not publish settings/server-endpoint.json: {error}")

    prepare(display_host, port)

    try:
        from services.server_lifecycle import run_until_stopped
        run_until_stopped(api, host=host, port=port, sockets=[listener])
    except OSError as e:
        # The probe above narrows this to a genuine race (port taken in the
        # window between probe and uvicorn's own bind). Still fail loudly and
        # actionably rather than dumping a bare traceback into the launcher.
        print(
            f"\n[HocusPocus Lab] ERROR: failed to bind {host}:{port} ({e}). "
            f"The port was taken just after we checked it — Start again to "
            f"pick a fresh port.\n",
            flush=True,
        )
        sys.exit(1)
