from biosafe.application.funcall_detector import detect_funcall


def test_show_procedure_panel_hit() -> None:
    result = detect_funcall("现在第几步了")
    assert result is not None
    assert result.command == "ShowProcedurePanel"


def test_current_experiment_operation_hit() -> None:
    result = detect_funcall("这一步怎么操作")
    assert result is not None
    assert result.command == "CurrentExperimentOperation"


def test_switch_experiment_scene_hit() -> None:
    result = detect_funcall("切换到PCR实验")
    assert result is not None
    assert result.command == "SwitchExperimentScene"


def test_enter_experiment_scene_hit() -> None:
    result = detect_funcall("进入PCR实验")
    assert result is not None
    assert result.command == "SwitchExperimentScene"


def test_enter_laboratory_protection_question_is_not_funcall() -> None:
    assert detect_funcall("进入生物安全实验室时，应当佩戴什么防护？") is None


def test_open_laboratory_door_question_is_not_funcall() -> None:
    assert detect_funcall("打开实验室门前需要注意什么？") is None


def test_excluded_by_condition_clause() -> None:
    assert detect_funcall("如果离心机出了问题这步怎么办") is None


def test_excluded_by_long_technical_sentence() -> None:
    assert detect_funcall("加完样之后下一步怎么做") is None
