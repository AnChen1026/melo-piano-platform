"""需求解析輸出的驗證：不合規格就丟例外，呼叫端改用規則解析。"""

import json

import pytest

from backend.course_parser_spec import FIELDS, InvalidParse, parse_output, target_json, transcript


def output(**changes):
    base = {"intent": "course_search", "level": None, "delivery_mode": None, "region": None,
            "max_price": None, "time_slot": None, "search_query": ""}
    return json.dumps({**base, **changes}, ensure_ascii=False)


def test_valid_output_is_normalized():
    result = parse_output("好的：" + output(region="臺中市西屯區", max_price=1200, search_query=" 爵士即興 "))
    assert result["region"] == "台中市西屯區"
    assert result["search_query"] == "爵士即興"


@pytest.mark.parametrize(
    "text",
    [
        "不是 JSON",
        output(intent="chitchat"),
        output(level="高級"),
        output(region="台中"),
        output(max_price="1000"),
        output(max_price=True),
        output(time_slot="平日上午"),
        json.dumps({"intent": "course_search"}),
    ],
)
def test_invalid_output_is_rejected(text):
    with pytest.raises(InvalidParse):
        parse_output(text)


def test_target_json_has_fixed_field_order_and_transcript_labels_roles():
    assert list(json.loads(target_json({"intent": "off_topic"}))) == list(FIELDS)
    assert transcript([{"role": "user", "content": "想學琴 "}, {"role": "assistant", "content": "程度？"}]) == "學生：想學琴\n顧問：程度？"
