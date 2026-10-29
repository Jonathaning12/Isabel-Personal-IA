"""Unit tests for the skill store and program building."""

import json

import pytest
from pydantic import ValidationError

from assistant.skills.store import Skill, SkillError, SkillStore, build_program


def skill(**overrides) -> Skill:
    data = {
        "name": "calcular_ahorro",
        "description": "Meses para un objetivo",
        "parameters": ["ahorro_mensual", "objetivo"],
        "code": "print(params['objetivo'] / params['ahorro_mensual'])",
    }
    return Skill(**{**data, **overrides})


def test_save_list_get_delete(tmp_path):
    store = SkillStore(tmp_path / "skills.json")

    saved, created = store.save(skill())
    assert created is True and saved.created_at
    _, created_again = store.save(skill(description="nueva"))
    assert created_again is False
    assert [s.description for s in store.list()] == ["nueva"]
    assert store.get("calcular_ahorro").name == "calcular_ahorro"

    assert store.delete("calcular_ahorro") is True
    assert store.delete("calcular_ahorro") is False
    with pytest.raises(SkillError):
        store.get("calcular_ahorro")


def test_skills_persist_on_disk(tmp_path):
    SkillStore(tmp_path / "skills.json").save(skill())
    assert "calcular_ahorro" in json.loads((tmp_path / "skills.json").read_text())
    assert SkillStore(tmp_path / "skills.json").get("calcular_ahorro")


@pytest.mark.parametrize(
    "overrides",
    [{"name": "Bad Name"}, {"name": "x"}, {"parameters": ["1abc"]}, {"code": ""}],
)
def test_invalid_skills_are_rejected(overrides):
    with pytest.raises(ValidationError):
        skill(**overrides)


def test_program_injects_params_as_data():
    program = build_program(skill(), {"ahorro_mensual": 300, "objetivo": 6000})
    namespace: dict = {}
    exec(program.replace("print(", "result = ("), namespace)  # run without the sandbox
    assert namespace["params"] == {"ahorro_mensual": 300, "objetivo": 6000}
    assert namespace["result"] == 20


def test_param_values_cannot_inject_code():
    evil = "'); import os; os.system('rm -rf /'); ('"
    program = build_program(skill(), {"ahorro_mensual": evil, "objetivo": 1})
    namespace: dict = {}
    exec(program.split("\n\n", 1)[0], namespace)  # only the params line
    assert namespace["params"]["ahorro_mensual"] == evil  # stays a plain string


def test_missing_or_unknown_params_are_rejected():
    with pytest.raises(SkillError):
        build_program(skill(), {"ahorro_mensual": 1})
    with pytest.raises(SkillError):
        build_program(skill(), {"ahorro_mensual": 1, "objetivo": 2, "extra": 3})
