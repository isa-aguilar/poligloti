"""The demo learner loads and every progress screen can read it."""

from __future__ import annotations

from backend import config, memory, syllabus
from scripts import load_demo


def test_demo_loads_and_is_readable(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    assert load_demo.main() == 0
    tracker = memory.read_skill_tracker("alex", "en")
    assert tracker["cefr"] == "B1"
    assert all(v is not None for v in tracker["scores"].values())
    assert len(memory.read_skill_history("alex", "en")) == 3
    assert memory.has_assessment("alex", "en")
    assert memory.read_curriculum("alex", "en")["focus"].startswith("Present perfect")
    assert syllabus.read_user_syllabus("alex", "en")["b1-01"]["status"] == "practiced"
    assert syllabus.topic_by_id("en", "b1-01") is not None
    # Loading twice never overwrites.
    (tmp_path / "alex" / "en" / "USER.md").write_text("changed", encoding="utf-8")
    load_demo.main()
    assert (tmp_path / "alex" / "en" / "USER.md").read_text(encoding="utf-8") == "changed"
