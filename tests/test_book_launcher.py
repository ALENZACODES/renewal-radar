import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("broker_launcher_test", ROOT / "tools" / "launch_local.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class Response:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.data[:limit]


@pytest.mark.parametrize("version", [17, 19, 20, 21])
def test_launcher_recognizes_versioned_application_shell(monkeypatch, version):
    source = f"const shellCacheName = 'renewal-radar-shell-v{version}';".encode()
    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda *a, **k: Response(source))
    assert launcher.is_running(8029)


@pytest.mark.parametrize("data", [b"other app", b"", b"renewal-radar-shell-v20", b"const shellCacheName = 'other-app';"])
def test_launcher_does_not_misidentify_unrelated_services(monkeypatch, data):
    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda *a, **k: Response(data))
    assert not launcher.is_running(8029)


def test_launcher_handles_an_unavailable_server(monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("unavailable")
    monkeypatch.setattr(launcher.urllib.request, "urlopen", unavailable)
    assert not launcher.is_running(8029)
