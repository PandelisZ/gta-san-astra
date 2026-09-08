#!/usr/bin/env python3
"""Read-only native integration checks plus neutral waits; requires running PCSX2.

No game keys, pause hotkeys, or frame advances are sent. Screenshots are temporary.
"""
import json
import pathlib
import signal
import struct
import subprocess
import tempfile
import time

BRIDGE = pathlib.Path(__file__).resolve().parent / 'astra-bridge'
checks = 0

def run(*args, success=True):
    global checks
    p = subprocess.run([str(BRIDGE), *args], capture_output=True, text=True, timeout=10)
    value = json.loads(p.stdout)
    assert value['ok'] is success, (args, value, p.stderr)
    assert (p.returncode == 0) is success, (args, p.returncode)
    checks += 1
    return value

status = run('status')
assert status['accessibility'] and status['screenRecording'], status
run('windows')
for args in [
    ('input', '--keys', 'invalid'),
    ('input', '--keys', '', '--duration-ms', '-1'),
    ('input', '--keys', '', '--duration-ms', '10001'),
    ('input', '--keys', '', '--duration-ms', 'garbage'),
    ('step', '--keys', '', '--frames', '0'),
    ('step', '--keys', '', '--frames', '121'),
    ('step', '--keys', '', '--frame-interval-ms', '9'),
    ('step', '--keys', '', '--frame-key', 'invalid'),
    ('step', '--keys', 'n', '--frames', '1'),
    ('status', '--pid', str(__import__('os').getpid())),
]:
    run(*args, success=False)
neutral = run('input', '--keys', '', '--duration-ms', '30')
assert neutral['requestedDurationMs'] == 30 and neutral['elapsedMs'] >= 30, neutral
# Exercise signal cleanup without changing any emulator key state.
for sig in (signal.SIGINT, signal.SIGTERM):
    p = subprocess.Popen([str(BRIDGE), 'input', '--keys', '', '--duration-ms', '10000'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(0.3)
    p.send_signal(sig)
    p.communicate(timeout=2)
    assert p.returncode == 128 + sig, p.returncode
    checks += 1
with tempfile.TemporaryDirectory(prefix='astra-native-') as directory:
    full = run('capture', '--output', str(pathlib.Path(directory) / 'full.png'))
    crop = run('capture', '--output', str(pathlib.Path(directory) / 'crop.png'), '--crop-top', '32')
    assert crop['height'] == full['height'] - 32 and crop['width'] == full['width']
    for capture in (full, crop):
        data = pathlib.Path(capture['path']).read_bytes()
        assert data[:8] == b'\x89PNG\r\n\x1a\n'
        assert struct.unpack('>II', data[16:24]) == (capture['width'], capture['height'])
    for opt, value in [('--crop-top','-1'), ('--crop-top','999999'), ('--crop-top','garbage'), ('--window-id','garbage')]:
        run('capture', '--output', str(pathlib.Path(directory) / 'invalid.png'), opt, value, success=False)
print(f'{checks} native smoke checks passed')
