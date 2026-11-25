"""本地开发辅助：按 SQLAlchemy 模型建表（生产/验收请走 alembic upgrade head）。

用法：
    python -m app.iam.roles.init_db --database-url ...
"""

from __future__ import annotations

import argparse

from app.core.db import Base, build_engine
from app.iam.roles.cli import resolve_database_url


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.iam.roles.init_db",
        description="按模型建表（本地辅助，正式迁移见 alembic/）",
    )
    parser.add_argument("--database-url", default=None, help="覆盖 APP_DATABASE_URL")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    url = resolve_database_url(args.database_url)
    engine = build_engine(url)
    # 确保模型已注册到 metadata
    import app.iam.models  # noqa: F401
    import app.iam.roles.models  # noqa: F401

    Base.metadata.create_all(engine)
    print(f"已建表：{url}")
    return 0


if __name__ == "__main__":  # pragma: no cover - 命令行入口
    raise SystemExit(main())
