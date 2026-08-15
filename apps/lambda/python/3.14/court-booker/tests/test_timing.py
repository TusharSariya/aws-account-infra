import json

from booker.timing import Stopwatch


def test_stopwatch_emits_step_and_elapsed(capsys):
    clock = Stopwatch("upace_http", activity="court2")
    clock.mark("login")
    clock.mark("reserve")
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [row["step"] for row in lines] == ["login", "reserve"]
    assert all(row["timing"] is True and row["op"] == "upace_http" for row in lines)
    assert lines[0]["activity"] == "court2"
    assert lines[1]["elapsed_ms"] >= lines[0]["elapsed_ms"]
