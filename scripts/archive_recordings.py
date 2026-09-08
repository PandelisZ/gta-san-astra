#!/usr/bin/env python3
"""Archive explicitly selected finalized recordings; verify pixels/timestamps, never delete."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

from recording import ffmpeg_path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def frame_proof(ffmpeg: str, source: Path, destination: Path) -> tuple[dict, list]:
    subprocess.run([ffmpeg, '-hide_banner', '-nostdin', '-n', '-copyts', '-i', str(source),
                    '-map', '0:v:0', '-pix_fmt', 'rgb24', '-fps_mode', 'passthrough',
                    '-enc_time_base', '1:1000', '-f', 'framemd5', str(destination)],
                   capture_output=True, check=True)
    header, rows = {}, []
    for line in destination.read_text().splitlines():
        if line.startswith(('#tb ', '#dimensions ', '#sar ')):
            name, value = line.split(':', 1)
            header[name] = value.strip()
        elif line and not line.startswith('#'):
            rows.append(tuple(value.strip() for value in line.split(',')))
    return header, rows


def archive(ffmpeg: str, source: Path, folder: Path) -> dict:
    initial = source.stat()
    destination = folder / (source.stem + '.lossless-rgb.mkv')
    proof_path = destination.with_suffix('.verification.json')
    source_md5 = destination.with_suffix('.source.framemd5')
    archive_md5 = destination.with_suffix('.archive.framemd5')
    log_path = destination.with_suffix('.encode.log')
    for path in [destination, proof_path, source_md5, archive_md5, log_path]:
        if path.exists():
            raise FileExistsError(f'Refusing to overwrite {path}')
    source_sha = sha256(source)
    started = time.monotonic()
    command = [ffmpeg, '-hide_banner', '-nostdin', '-n', '-copyts', '-i', str(source),
               '-map', '0', '-c', 'copy', '-c:v:0', 'libx264rgb', '-crf', '0',
               '-preset', 'medium', '-pix_fmt', 'rgb24', '-fps_mode', 'passthrough',
               '-enc_time_base', '1:1000', str(destination)]
    with log_path.open('x') as log:
        subprocess.run(command, stdout=log, stderr=log, check=True)
    encode_seconds = time.monotonic() - started
    old_header, old_rows = frame_proof(ffmpeg, source, source_md5)
    new_header, new_rows = frame_proof(ffmpeg, destination, archive_md5)
    if old_header != new_header:
        raise ValueError(f'Dimensions/SAR/timebase differ for {source}')
    if not old_rows or len(old_rows) != len(new_rows):
        raise ValueError(f'Frame count mismatch/empty recording for {source}')
    duration_deltas = []
    for index, (old, new) in enumerate(zip(old_rows, new_rows)):
        if old[:3] + old[4:] != new[:3] + new[4:]:
            raise ValueError(f'Pixel hash, size or timestamp mismatch at frame {index} for {source}')
        if old[3] != new[3]:
            duration_deltas.append(int(new[3]) - int(old[3]))
    if any(abs(delta) > 1 for delta in duration_deltas):
        raise ValueError(f'Inferred frame duration changed by over 1ms for {source}')
    final = source.stat()
    if (initial.st_size, initial.st_mtime_ns) != (final.st_size, final.st_mtime_ns) or sha256(source) != source_sha:
        raise ValueError(f'Source changed during archival: {source}')
    proof = dict(source=str(source), archive=str(destination), source_sha256=source_sha,
                 archive_sha256=sha256(destination), source_bytes=initial.st_size,
                 archive_bytes=destination.stat().st_size, frames=len(old_rows),
                 rgb24_every_frame_bitexact=True, pts_dts_every_frame_identical=True,
                 dimensions_sar_timebase=old_header,
                 inferred_duration_mismatches=len(duration_deltas),
                 max_inferred_duration_difference_ms=max(map(abs, duration_deltas), default=0),
                 qualification='Decoded inferred durations may differ by 1ms; all RGB pixels and PTS/DTS match.',
                 first_frame=old_rows[0], last_frame=old_rows[-1],
                 source_framemd5=str(source_md5), archive_framemd5=str(archive_md5),
                 encode_seconds=encode_seconds, total_seconds=time.monotonic()-started,
                 encode_command=command, original_deleted=False)
    with proof_path.open('x') as stream:
        json.dump(proof, stream, indent=2)
        stream.write('\n')
    return dict(source=str(source), archive=str(destination), proof=str(proof_path),
                source_bytes=initial.st_size, archive_bytes=destination.stat().st_size,
                frames=len(old_rows), verified=True, encode_seconds=encode_seconds,
                total_seconds=proof['total_seconds'])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources', nargs='+', type=Path)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--verify', action='store_true', required=True)
    args = parser.parse_args()
    folder = args.destination.expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    sources = [path.expanduser().resolve(strict=True) for path in args.sources]
    if len(set(sources)) != len(sources):
        parser.error('Duplicate source paths')
    summary_path = folder / ('batch-' + time.strftime('%Y%m%d-%H%M%S') + '.json')
    ffmpeg = ffmpeg_path()
    records = []
    for source in sources:
        result = archive(ffmpeg, source, folder)
        records.append(result)
        summary = dict(records=records, source_bytes=sum(r['source_bytes'] for r in records),
                       archive_bytes=sum(r['archive_bytes'] for r in records), originals_deleted=False)
        summary_path.write_text(json.dumps(summary, indent=2)+'\n')
        print(json.dumps(result), flush=True)
    print(json.dumps({'summary':str(summary_path), **summary}), flush=True)


if __name__ == '__main__':
    main()
