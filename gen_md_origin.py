#!/usr/bin/env python3
"""為 Markdown 機械轉檔的 YAML 批次產生 md_origin/v1 證明。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path


SCHEMA = "md_origin/v1"
OUTPUT_NAME = "_md_origin.json"
AUX_FILES = (
    "caption_hashtag.md",
    "脆文_7篇.md",
    "_出貨檢查單_勾完.md",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_nn_map(value: str) -> tuple[str, str]:
    if value.count("=") != 1:
        raise argparse.ArgumentTypeError("--nn-map 格式必須是 <md 樣板>=<yaml 樣板>")
    md_template, yaml_template = (part.strip() for part in value.split("=", 1))
    if "{NN}" not in md_template or "{NN}" not in yaml_template:
        raise argparse.ArgumentTypeError("--nn-map 左右樣板都必須含 {NN}")
    return md_template, yaml_template


def md_pattern(template: str) -> re.Pattern[str]:
    escaped = re.escape(template).replace(re.escape("{NN}"), r"(?P<nn>\d{2})")
    if template.lower().endswith(".md"):
        return re.compile(rf"^{escaped}$")
    return re.compile(rf"^{escaped}.*\.md$")


def yaml_name(template: str, nn: str) -> str:
    name = template.replace("{NN}", nn)
    if Path(name).suffix.lower() not in {".yaml", ".yml"}:
        name += ".yaml"
    if Path(name).name != name:
        raise ValueError(f"yaml 樣板必須產生單層檔名：{name}")
    return name


def build_manifest(md_dir: Path, yaml_dir: Path, mapping: tuple[str, str]) -> dict:
    md_template, yaml_template = mapping
    pattern = md_pattern(md_template)
    records: list[dict[str, str]] = []
    seen_nn: set[str] = set()

    for source in sorted(md_dir.iterdir(), key=lambda path: path.name):
        if source.is_symlink() or not source.is_file():
            continue
        match = pattern.fullmatch(source.name)
        if not match:
            continue
        nn = match.group("nn")
        if nn in seen_nn:
            raise ValueError(f"md 映射出重複 NN={nn}")
        seen_nn.add(nn)
        target_name = yaml_name(yaml_template, nn)
        target = yaml_dir / target_name
        if target.is_symlink() or not target.is_file():
            raise ValueError(f"找不到 NN={nn} 對應 yaml：{target_name}")
        records.append(
            {"md": source.name, "sha256": sha256_file(source), "yaml": target_name}
        )

    if not records:
        raise ValueError(f"md 目錄內找不到符合樣板的原稿：{md_template}")

    actual_yamls = {
        path.name
        for path in yaml_dir.iterdir()
        if not path.is_symlink()
        and path.is_file()
        and path.name.lower().startswith("script_")
        and path.suffix.lower() in {".yaml", ".yml"}
        and not path.name.lower().endswith((".bak.yaml", ".bak.yml"))
    }
    listed_yamls = {record["yaml"] for record in records}
    if listed_yamls != actual_yamls:
        missing = sorted(actual_yamls - listed_yamls)
        extra = sorted(listed_yamls - actual_yamls)
        raise ValueError(f"yaml 清單無法一對一閉合（未映射={missing}；多映射={extra}）")

    aux: dict[str, str] = {}
    for name in AUX_FILES:
        path = md_dir / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"必要 aux 原檔不存在：{name}")
        aux[name] = sha256_file(path)

    return {
        "schema": SCHEMA,
        "source_md_dir": str(md_dir),
        "files": records,
        "aux": aux,
        "converted_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "converter": Path(__file__).name,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="產生 md_origin/v1 轉檔證明")
    parser.add_argument("--md-dir", required=True, help="Markdown 原稿夾")
    parser.add_argument("--yaml-dir", required=True, help="YAML 轉檔批次夾")
    parser.add_argument(
        "--nn-map",
        required=True,
        type=parse_nn_map,
        help="檔名映射，例：稿_n{NN}=script_溫蒂_05_{NN}",
    )
    args = parser.parse_args()

    md_dir_input = Path(args.md_dir).expanduser()
    yaml_dir_input = Path(args.yaml_dir).expanduser()
    if md_dir_input.is_symlink() or yaml_dir_input.is_symlink():
        parser.error("md/yaml 資料夾不得為符號連結")
    md_dir = md_dir_input.resolve()
    yaml_dir = yaml_dir_input.resolve()
    if not md_dir.is_dir():
        parser.error(f"--md-dir 不存在或不是資料夾：{md_dir}")
    if not yaml_dir.is_dir():
        parser.error(f"--yaml-dir 不存在或不是資料夾：{yaml_dir}")

    output = yaml_dir / OUTPUT_NAME
    if output.exists() or output.is_symlink():
        parser.error(f"拒絕覆寫既有證明：{output}")

    try:
        manifest = build_manifest(md_dir, yaml_dir, args.nn_map)
        with output.open("x", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"[PASS] 已產生 {output}")
    print(f"  files={len(manifest['files'])}，aux={len(manifest['aux'])}，schema={SCHEMA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
