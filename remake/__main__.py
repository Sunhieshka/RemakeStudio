"""Remake Studio CLI.

  python -m remake new --video in.mp4 --language Spanish --region Mexico [--title T] [--notes "..."]
  python -m remake new --script script.txt --language Spanish --region Spain
  python -m remake run <id> --from STAGE [--until STAGE] [--only C1,CLIP03]   (one stage unless --until)
  python -m remake status [<id>]
  python -m remake serve [--port 8100]

Stages: understand, localize, prompts, sheets, shots (video), assemble.
Review / edit the JSON in projects/<id>/ between stages; re-running a stage keeps finished items.
"""

from __future__ import annotations

import argparse
import json
import sys

from remake.project import STAGE_KEYS, STAGES, Project


def _print_status(p: Project) -> None:
    m = p.meta
    print(f"{m['id']}  {m['title']}  → {m['target']['language']} {m['target'].get('region', '')}")
    for key, label, _ in STAGES:
        s = m["stages"][key]
        line = f"  {label:<40} {s['status']}"
        if s.get("progress"):
            line += f"  ({s['progress']})"
        if s.get("result"):
            line += "  " + json.dumps(s["result"], ensure_ascii=False)
        print(line)
        if s.get("error"):
            print("    ! " + s["error"].replace("\n", "\n    ! "))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="remake", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="create a project")
    n.add_argument("--video", default="")
    n.add_argument("--script", default="", help="path to a .txt/.pdf script")
    n.add_argument("--language", required=True)
    n.add_argument("--region", default="")
    n.add_argument("--title", default="")
    n.add_argument("--notes", default="")
    n.add_argument("--resolution", default=None)
    n.add_argument("--ratio", default=None)

    r = sub.add_parser("run", help="run stages")
    r.add_argument("id")
    r.add_argument("--from", dest="start", choices=STAGE_KEYS, required=True)
    r.add_argument("--until", choices=STAGE_KEYS)
    r.add_argument("--only", default="", help="comma-separated item ids (sheets: C1,L2  shots: CLIP03)")

    s = sub.add_parser("status")
    s.add_argument("id", nargs="?")

    v = sub.add_parser("serve", help="web UI")
    v.add_argument("--port", type=int, default=8100)

    a = ap.parse_args(argv)

    if a.cmd == "new":
        script = ""
        if a.script:
            if a.script.lower().endswith(".pdf"):
                from remake.engine.pdf import extract_text
                script = extract_text(open(a.script, "rb").read())
            else:
                script = open(a.script, encoding="utf-8").read()
        settings = {k: getattr(a, k) for k in ("resolution", "ratio") if getattr(a, k)}
        p = Project.create(title=a.title, language=a.language, region=a.region, notes=a.notes,
                           video_path=a.video, script_text=script, settings=settings)
        print(p.id)
        return 0

    if a.cmd == "run":
        from remake import pipeline
        p = Project(a.id)
        only = [x.strip() for x in a.only.split(",") if x.strip()] or None
        try:
            pipeline.run(p, a.start, a.until, only=only)
        except Exception as e:
            print(f"error: {e}", file=sys.stderr)
            _print_status(p)
            return 1
        _print_status(p)
        return 0

    if a.cmd == "status":
        for m in ([Project(a.id).meta] if a.id else Project.list()):
            _print_status(Project(m["id"]))
        return 0

    if a.cmd == "serve":
        from remake.server import serve
        serve(a.port)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
