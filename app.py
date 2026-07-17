#!/usr/bin/env python3
"""LW700Print web UI launcher.

    python app.py            # launch server, open browser
    python app.py --no-open  # server only
    python app.py --port 8099

The editor renders labels through the same bitmap pipeline that will feed the
USB printer. Until the ESCPL2 protocol is decoded, "Print" falls back to saving
the exact print bitmap as PNG (output/).
"""
import argparse
import csv
import io
import os
import sys
import threading
import webbrowser

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from fastapi import FastAPI, Request, UploadFile  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from lw700 import backends, fonts, render  # noqa: E402
from lw700.spec import MAX_LINES, MIN_LINES, TAPES  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
OUTPUT = os.path.join(HERE, "output")

app = FastAPI(title="LW700Print")
_stop = {"flag": False}


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/api/meta")
def meta():
    return {
        "fonts": fonts.available_fonts(),
        "tapes": [{"mm": t.width_mm, "dots": t.printable_dots} for t in TAPES.values()],
        "min_lines": MIN_LINES,
        "max_lines": MAX_LINES,
        "label_types": ["text", "qr", "barcode", "text_qr", "image", "image_text",
                        "cable_flag", "image_flag", "qr_flag", "cable_wrap", "patch_panel"],
        "barcode_types": ["code128", "code39", "ean13", "ean8", "upca", "isbn13"],
        "aligns": ["left", "center", "right"],
    }


@app.get("/api/status")
def status():
    st = backends.detect_status()
    return {"connected": st.connected, "tape_mm": st.tape_mm, "detail": st.detail,
            "media_ok": st.media_ok, "raw": st.raw}


@app.post("/api/render")
async def api_render(request: Request):
    spec = render.LabelSpec.from_dict(await request.json())
    img = render.render(spec)
    png = render.to_png_bytes(img, scale=3)
    return Response(
        content=png,
        media_type="image/png",
        headers={"X-Label-Dots": f"{img.width}x{img.height}",
                 "X-Label-Mm": f"{img.width / 180 * 25.4:.1f}x{spec.tape_mm}"},
    )


@app.post("/api/print")
async def api_print(request: Request):
    data = await request.json()
    spec = render.LabelSpec.from_dict(data)
    img = render.render(spec)
    prefer_usb = bool(data.get("use_usb", True))
    backend = backends.get_backend(prefer_usb, OUTPUT)
    try:
        msg = backend.print_label(img, tape_mm=spec.tape_mm)
        return {"ok": True, "backend": backend.name, "message": msg}
    except backends.NotReady as e:
        pv = backends.PreviewBackend(OUTPUT)
        msg = pv.print_label(img, tape_mm=spec.tape_mm)
        return {"ok": True, "backend": "preview", "message": f"{msg}", "note": str(e)}


@app.post("/api/csv")
async def api_csv(file: UploadFile):
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    rows = list(reader)[:1000]
    return {"columns": reader.fieldnames or [], "rows": rows, "count": len(rows)}


@app.post("/api/cut")
def api_cut():
    try:
        return {"ok": True, "message": backends.cut_tape()}
    except Exception as e:  # noqa: BLE001 - report any USB/printer error to the UI
        return {"ok": False, "message": str(e)}


@app.post("/api/stop")
def api_stop():
    _stop["flag"] = True
    return {"ok": True}


@app.post("/api/render_batch")
async def api_render_batch(request: Request):
    import base64
    data = await request.json()
    template = data.get("template", {})
    rows = data.get("rows", [])
    items = []
    for i, row in enumerate(rows[:1000]):
        spec = render.LabelSpec.from_dict(_apply_template(template, row))
        img = render.render(spec)
        png = render.to_png_bytes(img, scale=2, margins="left")
        items.append({
            "index": i,
            "png": "data:image/png;base64," + base64.b64encode(png).decode(),
            "mm": round(img.width / 180 * 25.4, 1),
            "tape_mm": spec.tape_mm,
        })
    return {"count": len(items), "items": items}


@app.post("/api/render_specs")
async def api_render_specs(request: Request):
    """Render a list of fully-built label specs (used by grouped multiline)."""
    import base64
    specs = (await request.json()).get("specs", [])
    items = []
    for i, sd in enumerate(specs[:1000]):
        spec = render.LabelSpec.from_dict(sd)
        img = render.render(spec)
        png = render.to_png_bytes(img, scale=2, margins="left")
        items.append({"index": i, "png": "data:image/png;base64," + base64.b64encode(png).decode(),
                      "mm": round(img.width / 180 * 25.4, 1), "tape_mm": spec.tape_mm})
    return {"count": len(items), "items": items}


@app.post("/api/print_specs")
async def api_print_specs(request: Request):
    data = await request.json()
    specs = data.get("specs", [])[:1000]
    prefer_usb = bool(data.get("use_usb", True))
    jobs = [_render_job(sd) for sd in specs]
    results = _run_batch(jobs, prefer_usb)
    return {"ok": True, "count": len(results), "results": results, "stopped": _stop["flag"]}


@app.post("/api/print_batch")
async def api_print_batch(request: Request):
    data = await request.json()
    template = data.get("template", {})
    rows = data.get("rows", [])[:1000]
    prefer_usb = bool(data.get("use_usb", True))
    jobs = [_render_job(_apply_template(template, row)) for row in rows]
    results = _run_batch(jobs, prefer_usb)
    return {"ok": True, "count": len(results), "results": results, "stopped": _stop["flag"]}


def _render_job(spec_dict: dict):
    spec = render.LabelSpec.from_dict(spec_dict)
    return render.render(spec), spec.tape_mm


def _run_batch(jobs, prefer_usb: bool):
    """Print a whole batch over one USB connection; fall back to preview if not ready."""
    _stop["flag"] = False
    if prefer_usb and backends.detect_status().connected:
        try:
            return backends.print_labels_usb(jobs, should_stop=lambda: _stop["flag"])
        except backends.NotReady:
            pass
    pv = backends.PreviewBackend(OUTPUT)
    out = []
    for i, (img, tape) in enumerate(jobs):
        if _stop["flag"]:
            out.append(f"STOPPED after {i}")
            break
        out.append(pv.print_label(img, tape_mm=tape))
    return out


def _apply_template(template: dict, row: dict) -> dict:
    def sub(s):
        if not isinstance(s, str):
            return s
        for k, v in row.items():
            s = s.replace("{" + k + "}", str(v))
        return s

    out = dict(template)
    out["lines"] = [
        {**ln, "text": sub(ln.get("text", ""))} for ln in template.get("lines", [])
    ]
    out["code_data"] = sub(template.get("code_data", ""))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    os.makedirs(OUTPUT, exist_ok=True)
    url = f"http://{args.host}:{args.port}/"
    if not args.no_open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"LW700Print UI -> {url}")

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
