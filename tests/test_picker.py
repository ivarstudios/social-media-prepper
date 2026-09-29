import subprocess
import types

from smp import picker


def fake_run(stdout, code=0):
    calls = []

    def run(args, **kw):
        calls.append(args)
        return types.SimpleNamespace(stdout=stdout, returncode=code)
    return run, calls


def test_windows_and_fallback_use_tk_in_a_separate_process(monkeypatch, tmp_path):
    run, calls = fake_run("C:/Photos/2024 Summer trip")
    monkeypatch.setattr(picker.platform, "system", lambda: "Windows")
    monkeypatch.setattr(subprocess, "run", run)
    assert picker.pick_folder(str(tmp_path)).replace("\\", "/") == "C:/Photos/2024 Summer trip"
    assert "askdirectory" in calls[0][2] and calls[0][3] == str(tmp_path)


def test_cancel_returns_empty(monkeypatch):
    run, _ = fake_run("")
    monkeypatch.setattr(picker.platform, "system", lambda: "Windows")
    monkeypatch.setattr(subprocess, "run", run)
    assert picker.pick_folder("") == ""


def test_mac_uses_finder(monkeypatch, tmp_path):
    run, calls = fake_run("/Users/anna/Photos/Set/\n")
    monkeypatch.setattr(picker.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(subprocess, "run", run)
    assert picker.pick_folder(str(tmp_path)) == "/Users/anna/Photos/Set"
    assert calls[0][0] == "osascript" and "choose folder" in calls[0][2]


def test_missing_initial_folder_is_ignored(monkeypatch):
    run, calls = fake_run("")
    monkeypatch.setattr(picker.platform, "system", lambda: "Windows")
    monkeypatch.setattr(subprocess, "run", run)
    picker.pick_folder("Z:/does/not/exist")
    assert calls[0][3] == ""
