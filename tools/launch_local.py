"""Launch the local application using installed dependencies or a local virtualenv."""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser


ROOT = Path(__file__).resolve().parents[1]


def runtime_environment(root=ROOT):
    config_path = root / 'local-runtime.json'
    config = json.loads(config_path.read_text(encoding='utf-8-sig')) if config_path.exists() else {}
    dependency_path = config.get('dependency_directory')
    directories = [str(root / 'backend')]
    if dependency_path and Path(dependency_path).is_dir():
        directories.insert(0, str(Path(dependency_path).resolve()))
    elif (root / 'work' / '.pydeps').is_dir():
        directories.insert(0, str(root / 'work' / '.pydeps'))
    environment = dict(os.environ)
    environment['PYTHONPATH'] = os.pathsep.join(directories)
    port = config.get('port', 8017)
    if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
        raise ValueError('Local application port must be between 1024 and 65535')
    return environment, port


def is_running(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/service-worker.js', timeout=1) as response:
            return re.search(
                rb"const\s+shellCacheName\s*=\s*['\"]renewal-radar-shell-v\d+['\"]",
                response.read(10000),
            ) is not None
    except (OSError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--no-install', action='store_true')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    environment, port = runtime_environment()
    if is_running(port):
        if not args.no_browser and not args.check:
            webbrowser.open(f'http://127.0.0.1:{port}')
        print(f'http://127.0.0.1:{port}')
        return 0
    python = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    executable = str(python) if python.exists() else sys.executable
    probe = subprocess.run([executable, '-c', 'import uvicorn, fastapi, fitz, sqlalchemy, httpx'], env=environment,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if probe.returncode:
        if args.no_install or args.check:
            print('Application dependencies are not installed.', file=sys.stderr)
            return 1
        subprocess.run([sys.executable, '-m', 'venv', str(ROOT / '.venv')], check=True)
        executable = str(python)
        subprocess.run([executable, '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')], check=True)
    if args.check:
        print('Local runtime dependencies verified.')
        return 0
    with socket.socket() as connection:
        if connection.connect_ex(('127.0.0.1', port)) == 0:
            raise RuntimeError(f'Port {port} is used by another application')
    logs = ROOT / 'data'
    logs.mkdir(exist_ok=True)
    with (logs / 'local-server.log').open('ab') as output:
        process = subprocess.Popen([executable, '-m', 'uvicorn', 'renewal.main:app', '--host', '127.0.0.1', '--port', str(port)],
                                   cwd=ROOT, env=environment, stdout=output, stderr=output,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    for _ in range(60):
        if process.poll() is not None:
            raise RuntimeError('Application server stopped; see data/local-server.log')
        if is_running(port):
            print(f'http://127.0.0.1:{port}')
            if not args.no_browser:
                webbrowser.open(f'http://127.0.0.1:{port}')
            return 0
        time.sleep(0.5)
    raise RuntimeError('Local application did not become ready; see data/local-server.log')


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
