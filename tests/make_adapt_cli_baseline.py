"""生成 adapt.py 子命令的对拍基线 tests/baselines/adapt_cli.json。

必须用改动前的干净副本跑，别用当前工作区（工作区随时会被改）：
  git archive <sha> | tar -x -C /tmp/aac-adapt-base
  .venv/bin/python tests/make_adapt_cli_baseline.py /tmp/aac-adapt-base <sha>
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import adapt_cli_cases
import adapt_cli_driver

OUT = HERE / "baselines" / "adapt_cli.json"
HOW = "git archive <sha> | tar -x -C /tmp/aac-adapt-base && .venv/bin/python tests/make_adapt_cli_baseline.py /tmp/aac-adapt-base <sha>"


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    root, sha = Path(argv[0]), argv[1]
    cases = {}
    for spec in adapt_cli_cases.CASES:
        with tempfile.TemporaryDirectory() as work:
            cases[spec["name"]] = adapt_cli_driver.run_once(root, spec, work)
        print(f"{spec['name']}\trc={cases[spec['name']]['rc']}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"provenance": {"baseline": sha, "how": HOW, "cases": len(cases)},
                               "cases": cases}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
