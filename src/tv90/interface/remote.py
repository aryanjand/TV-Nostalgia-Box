"""Parent LAN remote. Four buttons and now playing; no catalog."""

from __future__ import annotations

from http import HTTPStatus

from flask import Flask, redirect, render_template_string
from werkzeug.wrappers.response import Response

from tv90.application.television import TelevisionController

# T15 binds these. 0.0.0.0 is every interface on the Pi (home LAN).
# Do not publish this socket on a public WAN without NAT.
REMOTE_BIND_HOST = "0.0.0.0"
REMOTE_BIND_PORT = 5000

CHANNEL_UP_PATH = "/channel/up"
CHANNEL_DOWN_PATH = "/channel/down"
VOLUME_UP_PATH = "/volume/up"
VOLUME_DOWN_PATH = "/volume/down"

# Inline CSS only: the page must work with no network and no extra files.
_REMOTE_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>90s TV Remote</title>
  <style>
    body {
      margin: 0;
      padding: 1.5rem;
      background: #1a1a1a;
      color: #f2f2f2;
      font-family: system-ui, sans-serif;
    }
    h1 {
      margin: 0 0 0.75rem;
      font-size: 1.25rem;
      letter-spacing: 0.04em;
    }
    .now-playing {
      margin: 0 0 2rem;
      font-size: 1.5rem;
      line-height: 1.4;
      word-break: break-word;
    }
    form { margin: 0 0 1rem; }
    button {
      display: block;
      width: 100%;
      min-height: 4.5rem;
      padding: 0.75rem 1rem;
      border: 0;
      border-radius: 0.75rem;
      background: #2f6f4e;
      color: #ffffff;
      font-size: 1.5rem;
      font-weight: 700;
      letter-spacing: 0.06em;
    }
    button.volume { background: #3d4f7a; }
  </style>
</head>
<body>
  <h1>Now Playing</h1>
  <p class="now-playing">{{ now_playing }}</p>
  <form method="post" action="/channel/up">
    <button type="submit">CHANNEL UP</button>
  </form>
  <form method="post" action="/channel/down">
    <button type="submit">CHANNEL DOWN</button>
  </form>
  <form method="post" action="/volume/up">
    <button class="volume" type="submit">VOLUME UP</button>
  </form>
  <form method="post" action="/volume/down">
    <button class="volume" type="submit">VOLUME DOWN</button>
  </form>
</body>
</html>
"""


def create_remote_app(controller: TelevisionController) -> Flask:
    """Build the parent remote. Does not listen; T15 calls app.run."""
    # No static folder: Flask must not grow a file-listing URL.
    app = Flask(__name__, static_folder=None)

    @app.get("/")
    def home() -> str:
        return render_template_string(
            _REMOTE_PAGE, now_playing=controller.now_playing()
        )

    @app.post(CHANNEL_UP_PATH)
    def channel_up() -> Response:
        controller.channel_up()
        return _redirect_home()

    @app.post(CHANNEL_DOWN_PATH)
    def channel_down() -> Response:
        controller.channel_down()
        return _redirect_home()

    @app.post(VOLUME_UP_PATH)
    def volume_up() -> Response:
        controller.volume_up()
        return _redirect_home()

    @app.post(VOLUME_DOWN_PATH)
    def volume_down() -> Response:
        controller.volume_down()
        return _redirect_home()

    return app


def _redirect_home() -> Response:
    return redirect("/", code=HTTPStatus.SEE_OTHER)
