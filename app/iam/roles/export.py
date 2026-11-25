"""把 role_matrix.yml 渲染成 Markdown 矩阵表。

用法：
    python -m app.iam.roles.export                     # 写到 docs/role_matrix.md
    python -m app.iam.roles.export --output path.md

表结构：行为权限点，列为角色，单元格为数据范围（self / site / org），`—` 表示无此权限。
表格由 yml 生成，不要手改；改了矩阵请重跑本脚本。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.iam.roles.matrix import (
    Matrix,
    MatrixError,
    action_of,
    load_matrix,
    matrix_path,
)

# 默认输出位置（仓库根目录下的 docs/）
DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "docs" / "role_matrix.md"

EMPTY_CELL = "—"

# 仓库根目录（app/iam/roles/export.py → 上溯三级）
REPO_ROOT = Path(__file__).resolve().parents[3]


def _display_source(path: Path) -> str:
    """尽量用仓库相对路径展示真源文件位置。"""
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)

HEADER = (
    "# 角色-权限矩阵\n"
    "\n"
    "> 本表由 `app/iam/roles/role_matrix.yml` 生成（`python -m app.iam.roles.export`），"
    "**请勿手改**。\n"
    "> 行 = 权限点，列 = 角色，单元格 = 数据范围：`self`（仅本人）/ `site`（本会所）/ "
    "`org`（全组织）；`—` 表示该角色没有这个权限点。\n"
    "> 数据库由同一份 yml 播种（`python -m app.iam.roles.seed`），"
    "一致性由 `python -m app.iam.roles.compare` 保证。\n"
)


def render_markdown(matrix: Matrix, *, source: str | None = None) -> str:
    """渲染 Markdown 矩阵表。"""
    lines: list[str] = [HEADER]
    source = source or _display_source(matrix_path())
    lines.append(f"> 矩阵版本：v{matrix.version}；组织：{matrix.org_name}（`{matrix.org_id}`）；"
                 f"权限点白名单：{len(matrix.permission_codes)} 条；角色：{len(matrix.roles)} 个。\n")
    lines.append(f"> 真源文件：`{source}`\n")

    # 角色定义表
    lines.append("## 1. 角色定义\n")
    lines.append("| 角色 code | 名称 | 层级 | 内置 | 说明 |")
    lines.append("|---|---|---|---|---|")
    for role in matrix.roles:
        lines.append(
            f"| `{role.code}` | {role.name} | {role.level} | "
            f"{'是' if role.is_system else '否'} | {role.description} |"
        )
    lines.append("")

    # 权限矩阵：行=权限点，列=角色
    lines.append("## 2. 权限矩阵\n")
    header = "| 权限点 | 动作 | " + " | ".join(
        f"{role.code}<br>{role.name}" for role in matrix.roles
    ) + " |"
    lines.append(header)
    lines.append("|---" * (len(matrix.roles) + 2) + "|")
    for permission_code in matrix.permission_codes:
        cells = []
        for role in matrix.roles:
            scope = role.scope_of(permission_code)
            cells.append(scope if scope else EMPTY_CELL)
        lines.append(
            f"| `{permission_code}` | {action_of(permission_code)} | " + " | ".join(cells) + " |"
        )
    lines.append("")

    # 图例
    lines.append("## 3. 图例\n")
    lines.append("- 数据范围：`self` 仅本人数据；`site` 本会所数据；`org` 全组织数据。")
    lines.append("- 内置角色（`is_system=true`）不可删除，删除请求返回 409；"
                 "权限点可由系统管理员调整（运行时鉴权接入见另一单）。")
    lines.append("- 职责分离：系统管理员只持 `iam.` / `sys.` / `audit.` 权限，"
                 "不含任何 `crm.` / `opp.` / `lead.` 业务数据权限。")
    lines.append("- 管理层只持 `read` / `read_basic` / `use` 三种动作的权限点。")
    lines.append("")
    return "\n".join(lines)


def export_markdown(
    output: Path | str = DEFAULT_OUTPUT, *, matrix: Matrix | None = None
) -> Path:
    """渲染并写盘，返回写入路径。"""
    matrix = matrix or load_matrix()
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(matrix), encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.iam.roles.export",
        description="由 role_matrix.yml 生成 Markdown 权限矩阵表",
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="输出文件路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        matrix = load_matrix()
    except MatrixError as exc:
        print(f"矩阵文件不合法：{exc}", file=sys.stderr)
        return 2
    path = export_markdown(args.output, matrix=matrix)
    print(f"已生成矩阵表：{path}")
    print(f"角色 {len(matrix.roles)} 个，权限点 {len(matrix.permission_codes)} 条")
    return 0


if __name__ == "__main__":  # pragma: no cover - 命令行入口
    raise SystemExit(main())
