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
NOW_PLAYING_CHANNEL_PREFIX = "CH"
CHANNEL_BANNER_TOKEN_COUNT = 2

# Inline CSS only: the page must work with no network and no extra files.
_REMOTE_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>90s TV Remote</title>
  <style>
    :root {
      --crt-bg: #000000;
      --crt-green: #00ff00;
      --crt-green-dim: #146b14;
      --crt-text: #00ff00;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100dvh;
      padding: 1.25rem;
      background: var(--crt-bg);
      color: var(--crt-text);
      font-family: ui-monospace, "Cascadia Mono", "Segoe UI Mono", Menlo, Consolas,
        monospace;
    }
    main {
      position: relative;
      max-width: 28rem;
      margin: 0 auto;
    }
    .channel-bug {
      position: absolute;
      top: 0;
      right: 0;
      margin: 0;
      color: var(--crt-green);
      font-size: 3.4rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      line-height: 1;
    }
    .volume-osd {
      margin: 4.5rem 0 1.5rem;
    }
    .volume-label {
      margin: 0 0 0.45rem;
      color: var(--crt-green);
      font-size: 1.7rem;
      font-weight: 700;
      letter-spacing: 0.04em;
    }
    .volume-track {
      display: flex;
      align-items: center;
      gap: 0.28rem;
      min-height: 1.7rem;
    }
    .seg {
      display: block;
      flex: 1 1 0;
      height: 1.35rem;
    }
    .seg.on {
      background: var(--crt-green);
    }
    .seg.off {
      height: 0.42rem;
      border-radius: 50%;
      background: var(--crt-green);
    }
    h1 {
      margin: 0 0 0.5rem;
      color: var(--crt-green);
      font-size: 0.85rem;
      font-weight: 700;
      letter-spacing: 0.18em;
      text-transform: uppercase;
    }
    .now-playing {
      margin: 0 0 1.5rem;
      color: var(--crt-green);
      font-size: 1.15rem;
      line-height: 1.35;
      word-break: break-word;
    }
    .pad {
      display: grid;
      gap: 0.75rem;
    }
    form { margin: 0; }
    button {
      display: block;
      width: 100%;
      min-height: 4.5rem;
      padding: 0.75rem 1rem;
      border: 2px solid var(--crt-green);
      border-radius: 0;
      background: #001800;
      color: var(--crt-green);
      font-family: inherit;
      font-size: 1.35rem;
      font-weight: 700;
      letter-spacing: 0.12em;
    }
    button.volume { border-color: var(--crt-green-dim); }
  </style>
</head>
<body>
  <main>
    {% if channel_banner %}
    <p class="channel-bug">{{ channel_banner }}</p>
    {% endif %}
    <div class="volume-osd">
      <p class="volume-label">Volume</p>
      <div class="volume-track">
        {% for filled in volume_segments %}
        <span class="seg {% if filled %}on{% else %}off{% endif %}"></span>
        {% endfor %}
      </div>
    </div>
    <h1>Now Playing</h1>
    <p class="now-playing">{{ now_playing }}</p>
    <div class="pad">
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
    </div>
  </main>
</body>
</html>
"""


def create_remote_app(controller: TelevisionController) -> Flask:
    """Build the parent remote. Does not listen; T15 calls app.run."""
    # No static folder: Flask must not grow a file-listing URL.
    app = Flask(__name__, static_folder=None)

    @app.get("/")
    def home() -> str:
        now_playing = controller.now_playing()
        return render_template_string(
            _REMOTE_PAGE,
            now_playing=now_playing,
            channel_banner=_channel_banner_from_now_playing(now_playing),
            volume_segments=controller.volume_segments(),
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


def _channel_banner_from_now_playing(now_playing: str) -> str:
    tokens = now_playing.split()
    if (
        len(tokens) >= CHANNEL_BANNER_TOKEN_COUNT
        and tokens[0] == NOW_PLAYING_CHANNEL_PREFIX
    ):
        return f"{tokens[0]} {tokens[1]}"
    return ""
