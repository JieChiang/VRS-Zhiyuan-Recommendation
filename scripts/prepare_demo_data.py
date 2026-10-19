"""Copy synthetic template workbooks into an empty data directory; never overwrite."""
import argparse
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def prepare(target):
    target = Path(target).resolve()
    source = ROOT / "data_templates"
    files = sorted(source.glob("*.xlsx"))
    if len(files) != 14:
        raise ValueError("合成示例模板不完整，应包含14个Excel文件")
    if target == source.resolve() or (target.exists() and any(target.iterdir())):
        raise ValueError("目标目录必须不存在或为空，拒绝覆盖现有资料")
    target.mkdir(parents=True, exist_ok=True)
    for path in files:
        shutil.copy2(path, target / path.name)
    return len(files)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "demo")
    args = parser.parse_args()
    print(f"已准备{prepare(args.output)}个合成示例文件；所有院校、分数和计划均为虚构。")
