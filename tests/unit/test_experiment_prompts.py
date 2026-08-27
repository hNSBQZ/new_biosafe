from pathlib import Path

from biosafe.application.experiment_prompts import ExperimentPromptStore


def test_loads_legacy_experiment_markdown_and_builds_strict_json_prompt(tmp_path: Path) -> None:
    experiments = tmp_path / "experiments"
    experiments.mkdir()
    (experiments / "4.md").write_text(
        '''"EXP4": {
  title: "小鼠麻醉",
  context: `
    {
      "experiment_supplies": ["麻醉盒"],
      "experiment_steps": ["1. 放入麻醉盒"],
      "knowledge_points_list": ["常用吸入麻醉剂是异氟醚或乙醚。"]
    }
  `
}''',
        encoding="utf-8",
    )

    store = ExperimentPromptStore(experiments)

    assert store.list_experiments()[0].title == "小鼠麻醉"
    messages = store.build_messages("4", "小鼠常用吸入麻醉剂是什么？")
    assert messages[0]["role"] == "system"
    assert '"decision":"direct"' in messages[0]["content"]
    assert '"decision":"need_rag"' in messages[0]["content"]
    assert "常用吸入麻醉剂是异氟醚或乙醚" in messages[0]["content"]


def test_missing_experiment_uses_generic_prompt(tmp_path: Path) -> None:
    store = ExperimentPromptStore(tmp_path / "missing")
    messages = store.build_messages("missing", "问题")
    assert "当前没有绑定具体实验上下文" in messages[0]["content"]
