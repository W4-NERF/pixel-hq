"""Shared offline guards; individual tests replace external boundaries explicitly."""
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

pytest_plugins = ["tests.fixtures"]


@pytest.fixture(autouse=True)
def offline_only(tmp_path, monkeypatch):
    """No sockets or real CLIs, even if application code catches a denied attempt."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "isolated-home"))
    monkeypatch.delenv("HERMES_PROFILE", raising=False)
    denied = []
    def no_network(*args, **kwargs):
        denied.append("network")
        raise AssertionError("Tests must replace network access with a fake")
    for target, name in ((socket, "create_connection"), (socket, "getaddrinfo"),
                         (socket.socket, "connect"), (socket.socket, "connect_ex")):
        monkeypatch.setattr(target, name, no_network)
    popen = subprocess.Popen
    def local_probe_only(argv, *args, **kwargs):
        allowed = {"node", "python3", Path(sys.executable).name}
        if (not isinstance(argv, (list, tuple)) or not argv
                or Path(os.fsdecode(argv[0])).name not in allowed or kwargs.get("shell")
                or any(str(arg).startswith("hermes") for arg in argv[1:3])):
            denied.append("CLI")
            raise AssertionError("Tests may spawn only offline Python/Node probes; mock the Hermes CLI")
        return popen(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, "Popen", local_probe_only)
    yield
    assert denied == [], "A test attempted external IO: " + ", ".join(denied)
