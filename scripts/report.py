#!/usr/bin/env python3
"""Create a local HTML evidence gallery; manual ratings remain explicit annotations."""
import argparse
import html
import json
import os
from pathlib import Path
from statistics import median
from urllib.parse import quote


def load_lines(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def build_report(run_dir: Path, output: Path, annotations: dict | None = None):
    run_dir, output = run_dir.resolve(), output.resolve()
    decisions = load_lines(run_dir / "decisions.jsonl")
    events = [event for path in sorted(run_dir.rglob("events.jsonl")) for event in load_lines(path)]
    annotations = annotations or {}
    esc = lambda value: html.escape(str(value), quote=True)
    def picture(path):
        image = Path(path)
        if not image.is_file():
            return f'<p>Image unavailable: {esc(path)}</p>'
        url = esc(quote(os.path.relpath(image.resolve(), output.parent)))
        return f'<a href="{url}"><img loading="lazy" src="{url}" alt="Recorded game screenshot"></a>'
    rows = []
    latencies = []
    for event in decisions:
        if "decision" not in event:
            if event.get("type") not in ("error", "release_error"):
                continue
            rows.append(f'<article><h2>Run error</h2><pre>{esc(json.dumps(event, indent=2))}</pre></article>')
            continue
        decision = event["decision"]
        index = event["step"]
        latency = event.get("decision_latency_ms")
        if isinstance(latency, (int, float)):
            latencies.append(latency)
        annotation = annotations.get(str(index))
        annotation_text = json.dumps(annotation, indent=2) if annotation is not None else "Not manually evaluated"
        rows.append(f'''<article><h2>Decision {esc(index)}</h2>
          <div class="frames">{''.join(picture(path) for path in event.get('images', [])[-2:])}</div>
          <p><b>{esc(decision.get('scene', 'unknown'))}</b> · controls {esc(', '.join(decision.get('buttons', [])) or 'none')} · stop {esc(decision.get('stop'))}</p>
          <p>{esc(decision.get('rationale', ''))}</p>
          <p class="meta">Model latency {esc(latency)} ms · stride {esc(event.get('frame_stride', 'unknown'))} VSyncs · nominal observations/game-second {esc(event.get('nominal_observations_per_game_second', 'unknown'))}</p>
          <details><summary>Manual evaluation</summary><pre>{esc(annotation_text)}</pre></details></article>''')
    observed = {path for event in decisions for path in event.get("images", [])}
    # Include final observations and manually driven runs that have no model decisions.
    for event in events:
        path = event.get("image_path")
        if path and path not in observed:
            rows.append(f'<article><h2>Additional recorded observation</h2>{picture(path)}</article>')
            observed.add(path)
    summary_path = run_dir / "run_summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else None
    summary_html = (f'<details><summary>Run summary</summary><pre>{esc(json.dumps(summary, indent=2))}</pre></details>'
                    if summary is not None else "")
    latency_text = f"Median model latency: {median(latencies):.0f} ms." if latencies else "No model latency measurements."
    document = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>GTA San Astra evidence report</title><style>
body{{font:16px system-ui,sans-serif;background:#101316;color:#e9edf0;margin:0 auto;padding:32px;max-width:1100px;line-height:1.5}}
h1{{font-size:32px}}article{{border-top:1px solid #46505a;padding:24px 0}}img{{max-width:100%;max-height:420px;object-fit:contain;background:#000}}.frames{{display:flex;gap:12px}}.frames a{{flex:1;min-width:0}}.meta{{color:#bac5ce;font-size:14px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}a{{color:#b4dbff}}
</style><h1>GTA San Astra</h1><p>Recorded screenshots and model decisions. {len([e for e in decisions if 'decision' in e])} decisions. {latency_text}</p>
<p>Game-time cadence describes emulated VSyncs. The game pauses while the model decides, so wall-clock cadence differs. No automated driving score is inferred. Manual evaluation is shown only when supplied.</p>
{summary_html}{''.join(rows) if rows else '<p>No recorded evidence found.</p>'}</html>'''
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--annotations", type=Path, help='JSON object keyed by decision step; values are manual observations')
    args = parser.parse_args()
    print(build_report(args.run_dir, args.output or args.run_dir / "report.html",
                       json.loads(args.annotations.read_text()) if args.annotations else None))
