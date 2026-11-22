"""后台任务入口（争议超时提醒）。

⚠️ 工单原文：「争议提交后 10 天未处理时提醒负责人」。
⇒ 这里做成**可单独调用的 CLI**（`python -m app.tasks remind-disputes`），
    由外部 cron / K8s CronJob 触发 ⇒ 不在进程内起后台线程
    （进程内定时器在容器重启/多副本时会重复触发或漏触发）。
"""

from __future__ import annotations

import argparse
import sys

from app.db.session import session_scope
from app.services.dispute import remind_overdue_disputes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.tasks")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("remind-disputes", help="提醒超时未处理的争议")
    p.add_argument("--days", type=int, default=10)

    args = parser.parse_args(argv)
    if args.cmd == "remind-disputes":
        with session_scope() as sess:
            n = remind_overdue_disputes(sess, days=args.days)
        print(f"reminded={n}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
