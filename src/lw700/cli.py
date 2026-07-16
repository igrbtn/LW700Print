#!/usr/bin/env python3
"""Command-line interface for LW700Print.

Examples:
  python -m lw700 status
  python -m lw700 print --tape 12 --line "Server-01" --line "192.168.0.1"
  python -m lw700 print --type cable_flag --line "R4-1 1/1/1 | HOST01" --cable-dia 6
  python -m lw700 print --type qr --code "https://x" --line "Server-01"
  python -m lw700 render --out label.png --line "test"           # no printer
  python -m lw700 batch --csv labels.csv --type cable_flag --line "{marking}" --cable-dia 6
  python -m lw700 batch --csv labels.csv --template template.json
"""
import argparse
import csv
import json
import sys

from . import render
from .backends import PreviewBackend, USBBackend, detect_status


def _spec_from_args(a, overrides=None):
    d = {
        "tape_mm": a.tape, "label_type": a.type,
        "lines": [{"text": t} for t in (a.line or [])] or [{"text": ""}],
        "code_data": a.code or "", "barcode_type": a.barcode,
        "length_mode": "fixed" if a.length else "auto",
        "length_mm": a.length or 40, "margin_mm": a.margin,
        "line_spacing": a.line_spacing,
        "cable_diameter_mm": a.cable_dia, "wrap_mm": a.wrap,
        "repeat": a.repeat, "ports": a.ports,
    }
    if overrides:
        d.update(overrides)
    return render.LabelSpec.from_dict(d)


def _apply_row(template: dict, row: dict) -> dict:
    def sub(s):
        if not isinstance(s, str):
            return s
        for k, v in row.items():
            s = s.replace("{" + k + "}", str(v))
        return s
    out = dict(template)
    out["lines"] = [{**ln, "text": sub(ln.get("text", ""))} for ln in template.get("lines", [])]
    out["code_data"] = sub(template.get("code_data", ""))
    return out


def _print_img(img, tape_mm, preview_path=None, cut=True):
    if preview_path:
        img.convert("L").resize((img.width * 4, img.height * 4)).save(preview_path)
        return f"saved {preview_path}"
    st = detect_status()
    if not st.connected:
        return f"printer not connected ({st.detail})"
    return USBBackend().print_label(img, tape_mm=tape_mm, cut=cut)


def cmd_status(a):
    st = detect_status()
    print(json.dumps({"connected": st.connected, "tape_mm": st.tape_mm, "detail": st.detail},
                     ensure_ascii=False))


def cmd_print(a):
    spec = _spec_from_args(a)
    img = render.render(spec)
    print(_print_img(img, spec.tape_mm, a.out, not a.no_cut))


def cmd_render(a):
    spec = _spec_from_args(a)
    img = render.render(spec)
    out = a.out or "label.png"
    img.convert("L").resize((img.width * 4, img.height * 4)).save(out)
    print(f"saved {out} ({img.size[0]}x{img.size[1]} dots)")


def cmd_batch(a):
    template = None
    if a.template:
        with open(a.template, encoding="utf-8") as f:
            template = json.load(f)
    else:
        template = _spec_from_args(a).__dict__
        template = {
            "tape_mm": a.tape, "label_type": a.type,
            "lines": [{"text": t} for t in (a.line or ["{marking}"])],
            "code_data": a.code or "", "cable_diameter_mm": a.cable_dia,
            "line_spacing": a.line_spacing, "repeat": a.repeat, "ports": a.ports,
        }
    with open(a.csv, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    n = 0
    for row in rows:
        spec = render.LabelSpec.from_dict(_apply_row(template, row))
        img = render.render(spec)
        msg = _print_img(img, spec.tape_mm,
                         (a.out and f"{a.out.rsplit('.',1)[0]}_{n+1}.png"), not a.no_cut)
        print(f"[{n+1}/{len(rows)}] {msg}")
        n += 1
    print(f"batch done: {n} labels")


def build_parser():
    p = argparse.ArgumentParser(prog="lw700", description="LW-700 label printing CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--tape", type=int, default=18, help="tape width mm (6/9/12/18/24)")
        sp.add_argument("--type", default="text",
                        choices=["text", "qr", "barcode", "text_qr",
                                 "cable_flag", "cable_wrap", "patch_panel"])
        sp.add_argument("--line", action="append", help="text line (repeatable)")
        sp.add_argument("--code", help="QR/barcode data")
        sp.add_argument("--barcode", default="code128")
        sp.add_argument("--length", type=float, default=0, help="fixed length mm (0=auto)")
        sp.add_argument("--margin", type=float, default=3)
        sp.add_argument("--line-spacing", type=float, default=0.3, dest="line_spacing")
        sp.add_argument("--cable-dia", type=float, default=6, dest="cable_dia")
        sp.add_argument("--wrap", type=float, default=0)
        sp.add_argument("--repeat", type=int, default=4)
        sp.add_argument("--ports", type=int, default=12)
        sp.add_argument("--no-cut", action="store_true")
        sp.add_argument("--out", help="save PNG instead of printing (preview)")

    sub.add_parser("status", help="show printer/tape status").set_defaults(func=cmd_status)
    common(sub.add_parser("print", help="print one label"))
    sub.choices["print"].set_defaults(func=cmd_print)
    common(sub.add_parser("render", help="render to PNG (no printer)"))
    sub.choices["render"].set_defaults(func=cmd_render)
    b = sub.add_parser("batch", help="print labels from a CSV")
    common(b)
    b.add_argument("--csv", required=True, help="CSV with {placeholder} columns")
    b.add_argument("--template", help="label template JSON (else use --type/--line)")
    b.set_defaults(func=cmd_batch)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
