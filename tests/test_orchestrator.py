import main


def test_orchestrator_forces_utf8_for_child_scripts(monkeypatch):
    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(main.subprocess, "run", fake_run)

    main.run_script("child.py", "Test child", "RUN-UTF8")

    assert captured["env"]["PYTHONUTF8"] == "1"
    assert captured["env"]["PYTHONIOENCODING"] == "utf-8"
    assert captured["env"][main.RUN_ID_ENV] == "RUN-UTF8"
