# -*- coding: utf-8 -*-
"""结构化幅度代码勾稽、目标换算和依据校验。"""
import pytest

import typed_magnitude_probe as probe


TARGET_CASES = [
    (60, "调大", "模糊幅度", "小", 65),
    (60, "调大", "模糊幅度", "中", 70),
    (60, "调大", "模糊幅度", "大", 75),
    (60, "调小", "模糊幅度", "小", 55),
    (60, "调小", "模糊幅度", "中", 50),
    (60, "调小", "模糊幅度", "大", 45),
    (95, "调大", "模糊幅度", "大", 100),
    (3, "调小", "模糊幅度", "小", 0),
    (60, "调大", "明确变化量", 7, 67),
    (60, "调小", "明确变化量", 20, 40),
    (95, "调大", "明确变化量", 20, 100),
    (5, "调小", "明确变化量", 20, 0),
    (60, "调小", "明确目标值", 40, 40),
    (60, "调大", "明确目标值", 80, 80),
    (60, "不变", "明确目标值", 60, 60),
    (60, "调大", "极值", 100, 100),
    (60, "调小", "极值", 0, 0),
    (60, "不变", "明确变化量", 0, 60),
]


@pytest.mark.parametrize("current,direction,mtype,value,expected", TARGET_CASES)
def test_target_mapping(current, direction, mtype, value, expected):
    assert probe.target_from_fields(current, direction, mtype, value) == expected


@pytest.mark.parametrize("case", probe.build_cases(), ids=lambda case: case.case_id)
def test_all_expected_cases_pass_code_funnel(case):
    fields = {
        "direction": case.direction,
        "magnitude": {"type": case.magnitude_type, "value": case.magnitude_value},
        "adjustment_evidence": case.text,
    }
    valid, error, target = probe.validate_fields(fields, case.text, case.current)
    assert valid, error
    assert target == probe.expected_target(case)


INVALID_CASES = [
    (None, "参数不是对象"),
    ({}, "方向枚举非法"),
    ({"direction": "增加", "magnitude": {}, "adjustment_evidence": "调高"}, "方向枚举非法"),
    ({"direction": "调大", "magnitude": None, "adjustment_evidence": "调高"}, "幅度不是对象"),
    ({"direction": "调大", "magnitude": {"type": "未知", "value": 5},
      "adjustment_evidence": "调高5"}, "幅度类型非法"),
    ({"direction": "调大", "magnitude": {"type": "模糊幅度", "value": 5},
      "adjustment_evidence": "调高一点"}, "模糊幅度值必须是大中小"),
    ({"direction": "调大", "magnitude": {"type": "明确变化量", "value": "十"},
      "adjustment_evidence": "提高十"}, "明确数值必须是0到100整数"),
    ({"direction": "调大", "magnitude": {"type": "明确目标值", "value": 101},
      "adjustment_evidence": "调到101"}, "明确数值必须是0到100整数"),
    ({"direction": "调小", "magnitude": {"type": "极值", "value": 50},
      "adjustment_evidence": "调到最小"}, "极值只能是0或100"),
    ({"direction": "不变", "magnitude": {"type": "明确变化量", "value": 10},
      "adjustment_evidence": "保持不变"}, "不变的变化量必须是0"),
    ({"direction": "不变", "magnitude": {"type": "模糊幅度", "value": "中"},
      "adjustment_evidence": "声音小吗"}, "模糊幅度不能与不变组合"),
    ({"direction": "调大", "magnitude": {"type": "明确变化量", "value": 0},
      "adjustment_evidence": "提高0"}, "零变化量的方向必须是不变"),
    ({"direction": "调大", "magnitude": {"type": "明确目标值", "value": 40},
      "adjustment_evidence": "调到40"}, "方向与当前值和目标值不一致"),
    ({"direction": "调小", "magnitude": {"type": "极值", "value": 100},
      "adjustment_evidence": "调到最大"}, "方向与当前值和目标值不一致"),
    ({"direction": "调小", "magnitude": {"type": "模糊幅度", "value": "小"},
      "adjustment_evidence": "系统说降低一点"}, "依据不在当前用户原话中"),
]


@pytest.mark.parametrize("fields,error_fragment", INVALID_CASES)
def test_invalid_fields_fail_closed(fields, error_fragment):
    valid, error, target = probe.validate_fields(fields, "请降低一点音量", 60)
    assert not valid and error_fragment in error and target is None


def test_evidence_allows_normalized_punctuation_but_not_rewrite():
    fields = {"direction": "调小",
              "magnitude": {"type": "模糊幅度", "value": "小"},
              "adjustment_evidence": "降低一点音量"}
    valid, error, target = probe.validate_fields(
        fields, "请帮我，降低一点音量！", 60)
    assert valid and error is None and target == 55
    fields["adjustment_evidence"] = "把声音稍微调低"
    valid, error, target = probe.validate_fields(
        fields, "请帮我，降低一点音量！", 60)
    assert not valid and "依据不在" in error and target is None


def test_schema_has_exact_three_top_level_fields():
    props = probe.TOOL_SCHEMA["function"]["parameters"]["properties"]
    assert set(props) == {"direction", "magnitude", "adjustment_evidence"}
    branches = props["magnitude"]["anyOf"]
    assert len(branches) == 4
    assert all(set(branch["properties"]) == {"type", "value"}
               for branch in branches)
    assert {branch["properties"]["type"]["enum"][0]
            for branch in branches} == set(probe.MAGNITUDE_TYPES)
    fuzzy = next(branch for branch in branches
                 if branch["properties"]["type"]["enum"] == ["模糊幅度"])
    assert fuzzy["properties"]["value"]["enum"] == ["大", "中", "小"]
