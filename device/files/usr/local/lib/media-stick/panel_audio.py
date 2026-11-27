"""The «Звук» part of the panel: switch audio output between HDMI and 3.5mm jack.

POST /api/audio {"output": "hdmi" | "headphones"} validates, persists via
mediastick_audio.write_output, and applies immediately via mediastick_audio.apply_output.
When PipeWire is down, persistence still succeeds (`ok=True, applied=False`).

Standard library only, nothing happens on import.
"""
import mediastick_audio as audio
import panel_audio_ui as ui

PATH = "/api/audio"
MARKERS = {
    "@@AUDIO_ROW@@": ui.ROW,
    "@@AUDIO_SECTION@@": ui.SECTION,
    "@@AUDIO_TAIL@@": ui.TAIL,
}


def current():
    """Current audio output preference ('hdmi' or 'headphones') for /api/status."""
    return audio.read_output()


def post(path, body):
    """POST /api/audio: return (JSON-able reply, HTTP status code)."""
    if path != PATH:
        return {"ok": False, "error": "bad path"}, 404
    out = body.get("output") if isinstance(body, dict) else None
    if not isinstance(out, str) or out not in audio.VALID_OUTPUTS:
        return {"ok": False, "error": "bad output"}, 400
    try:
        audio.write_output(out)
    except OSError:
        return {"ok": False, "error": "failed to save audio output"}, 500
    res = audio.apply_output(out)
    return {"ok": True, "output": out, "applied": bool(res.get("applied"))}, 200


def inject(page):
    """Inject the audio settings row, section, and script into the panel HTML page."""
    for marker in MARKERS:
        if marker not in page:
            raise ValueError("the page has no %s: the audio setting cannot be put in" % marker)
    for marker, text in MARKERS.items():
        page = page.replace(marker, text, 1)
    return page
