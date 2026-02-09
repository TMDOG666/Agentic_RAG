import sys
from pathlib import Path

import json

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from grag.graph_construction.entity_relation_parser import parse_entity_relation_raw


def _paths() -> tuple[Path, Path]:
    base = Path(__file__).parent / "test_data"
    output_dir = base / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return base, output_dir


def _write_outputs(stem: str, payload: dict) -> None:
    _, output_dir = _paths()
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    (output_dir / f"{stem}.entity_relation_parsed.json").write_text(content, encoding="utf-8")


SAMPLE_RAW = "\n".join(
    [
        "entity<|SEP|>加勒特公爵<|SEP|>人物<|SEP|>北境守护者，在绝冬城被刺杀。",
        "entity<|SEP|>苍蓝历450年<|SEP|>时间<|SEP|>事件发生的时间。",
        "entity<|SEP|>绝冬城<|SEP|>地点<|SEP|>加勒特公爵遇刺的地点。",
        "entity<|SEP|>影刃<|SEP|>组织<|SEP|>执行刺杀行动的刺客组织。",
        "entity<|SEP|>维克多<|SEP|>人物<|SEP|>帝国宰相，刺杀行动的幕后策划者。",
        "entity<|SEP|>霜语<|SEP|>物品<|SEP|>加勒特公爵的佩剑，在事件中遗失。",
        "entity<|SEP|>兰斯<|SEP|>人物<|SEP|>流浪骑士，据传带走了“霜语”。",
        "entity<|SEP|>南北战争<|SEP|>事件<|SEP|>维克多策划刺杀意图引发的战争。",
        "relation<|SEP|>加勒特公爵<|SEP|>绝冬城<|SEP|>加勒特公爵在绝冬城驻守并遇害。<|SEP|>位于/遇害地<|SEP|>10",
        "relation<|SEP|>影刃<|SEP|>加勒特公爵<|SEP|>影刃组织的成员刺杀了加勒特公爵。<|SEP|>敌对_刺杀<|SEP|>10",
        "relation<|SEP|>维克多<|SEP|>影刃<|SEP|>维克多策划并指使影刃执行行动。<|SEP|>策划/指使<|SEP|>9",
        "relation<|SEP|>维克多<|SEP|>加勒特公爵<|SEP|>维克多策划了针对加勒特的刺杀。<|SEP|>敌对_谋杀<|SEP|>10",
        "relation<|SEP|>加勒特公爵<|SEP|>霜语<|SEP|>霜语是加勒特公爵的佩剑。<|SEP|>持有<|SEP|>10",
        "relation<|SEP|>兰斯<|SEP|>霜语<|SEP|>兰斯带走了遗失的霜语剑。<|SEP|>持有/带走<|SEP|>8",
        "relation<|SEP|>维克多<|SEP|>南北战争<|SEP|>维克多意图通过刺杀挑起南北战争。<|SEP|>引发/动机<|SEP|>9",
        "<|DONE|>",
    ]
)


def test_parse_entity_relation_raw_happy_path() -> None:
    parsed = parse_entity_relation_raw(SAMPLE_RAW)

    assert parsed.errors == []
    assert len(parsed.entities) == 8
    assert len(parsed.relations) == 7

    assert parsed.entities[0].name == "加勒特公爵"
    assert parsed.entities[0].type == "人物"

    assert parsed.relations[0].subject == "加勒特公爵"
    assert parsed.relations[0].object == "绝冬城"
    assert parsed.relations[0].confidence == 10

    _write_outputs(
        "happy_path",
        {
            "entities": [e.__dict__ for e in parsed.entities],
            "relations": [r.__dict__ for r in parsed.relations],
            "errors": parsed.errors,
        },
    )


def test_parse_entity_relation_raw_malformed_lines() -> None:
    raw = "\n".join(
        [
            "entity<|SEP|>只有两个字段",
            "relation<|SEP|>a<|SEP|>b<|SEP|>desc<|SEP|>type<|SEP|>not_int",
            "unknown<|SEP|>x<|SEP|>y",
            "<|DONE|>",
        ]
    )

    parsed = parse_entity_relation_raw(raw)

    assert len(parsed.entities) == 0
    assert len(parsed.relations) == 1
    assert parsed.relations[0].confidence is None
    assert len(parsed.errors) >= 2

    _write_outputs(
        "malformed_lines",
        {
            "entities": [e.__dict__ for e in parsed.entities],
            "relations": [r.__dict__ for r in parsed.relations],
            "errors": parsed.errors,
        },
    )


def run_tests() -> bool:
    tests = [
        ("解析成功", test_parse_entity_relation_raw_happy_path),
        ("异常行处理", test_parse_entity_relation_raw_malformed_lines),
    ]

    results: list[tuple[str, bool, str]] = []
    for name, fn in tests:
        try:
            fn()
            results.append((name, True, ""))
        except Exception as e:
            results.append((name, False, repr(e)))

    return all(ok for _, ok, _ in results)


if __name__ == "__main__":
    ok = run_tests()
    raise SystemExit(0 if ok else 1)
