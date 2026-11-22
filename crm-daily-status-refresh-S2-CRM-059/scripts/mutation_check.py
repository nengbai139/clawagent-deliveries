"""变异测试：把实现改坏，测试**必须**变红。

⚠️ **绿不算数**：全绿只说明「没崩」，不说明「测的是不是那个东西」。
⇒ 每条变异都指向一处**具体判断**，改坏之后必须有测试变红。

用法：`python scripts/mutation_check.py`
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (名称, 相对路径, 原文, 变异后)
MUTATIONS: list[tuple[str, str, str, str]] = [
    (
        "变异 1：分批条件写成 .where(where)（元组当成一个条件）",
        "crm/jobs/daily_status_refresh.py",
        "                .where(*where)",
        "                .where(where)",
    ),
    (
        "变异 2：失败批次不推进游标（会反复处理同一批）",
        "crm/jobs/daily_status_refresh.py",
        """            # ⚠️ 失败批次的行**也要推进游标** ⇒ 否则反复重试同一批 ⇒ 死循环。
            last_id = max(r.id for r in rows)""",
        """            # MUTANT: 失败批次不推进游标""",
    ),
    (
        "变异 3：状态没变化也照样写（幂等被破坏）",
        "crm/jobs/daily_status_refresh.py",
        """        if target == row.status:
            # ⚠️ **没变化就不动它**（连 updated_at 都不改）⇒
            # 幂等：第二次跑这行还是「没变化」⇒ 不写历史。
            continue""",
        """        # MUTANT: 没变化也照样写""",
    ),
    (
        "变异 4：不写变更历史",
        "crm/jobs/daily_status_refresh.py",
        "    record: Callable[..., Any] = record_change,",
        "    record: Callable[..., Any] = lambda *a, **k: None,  # MUTANT: 不写历史",
    ),
    (
        "变异 5：每次变化各自一个 operation_id（不是「一次运行共用一个」）",
        "crm/jobs/daily_status_refresh.py",
        """            operation_id=operation_id,
            effective_date=today,""",
        """            operation_id=uuid.uuid4().hex,  # MUTANT: 每次变化另算
            effective_date=today,""",
    ),
    (
        "变异 6：批次失败直接抛出（不继续下一批）",
        "crm/jobs/daily_status_refresh.py",
        """        except Exception as exc:  # noqa: BLE001 —— 批次失败要记录并继续
            sess.rollback()""",
        """        except Exception as exc:  # noqa: BLE001
            sess.rollback()
            raise""",
    ),
    (
        "变异 7：有失败批次也算 success（partial 判据被破坏）",
        "crm/jobs/daily_status_refresh.py",
        """    if not failed_batches:
        status = JOB_RUN_STATUS_SUCCESS""",
        """    if True:  # MUTANT
        status = JOB_RUN_STATUS_SUCCESS""",
    ),
    (
        "变异 8：会籍的人工状态也参与派生",
        "crm/models/entities.py",
        """MEMBERSHIP_STATUS_EXCLUDED: tuple[str, ...] = (
    MEMBERSHIP_STATUS_TERMINATED,
    MEMBERSHIP_STATUS_SUSPENDED,
)""",
        """MEMBERSHIP_STATUS_EXCLUDED: tuple[str, ...] = ()  # MUTANT""",
    ),
    (
        "变异 9：忽略 --date（永远按「今天」派生）",
        "crm/jobs/daily_status_refresh.py",
        """        today = (
            _parse_date(args.run_date)
            if args.run_date""",
        """        today = (
            date.today()  # MUTANT: 忽略 --date
            if args.run_date""",
    ),
    (
        "变异 10：改判后不回写状态（只写历史）",
        "crm/jobs/daily_status_refresh.py",
        """        before = row.status
        row.status = target""",
        """        before = row.status
        # MUTANT: 不回写状态""",
    ),
]

#: 单条变异最多跑多久（秒）⇒ **挂住也算失败**（变异可能引入死循环）。
TIMEOUT = 180


def run_one(name: str, rel: str, old: str, new: str) -> tuple[bool, str]:
    """跑一条变异。返回 (测试是否变红, 摘要)。"""
    path = ROOT / rel
    original = path.read_text()
    if old not in original:
        return False, f"!! 没找到待变异片段（源码变了？）"

    backup = tempfile.NamedTemporaryFile(delete=False, suffix=".bak")
    backup.close()
    shutil.copy2(path, backup.name)
    try:
        path.write_text(original.replace(old, new, 1))
        proc = subprocess.run(
            [".venv/bin/python", "-m", "pytest", "tests/", "-q", "--no-header", "-x"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            env={
                "PATH": "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin",
                "HOME": "/Users/baineng",
                "CRM_DATABASE_URL": "postgresql+psycopg://app:app@127.0.0.1:55433/app",
                "TEST_DATABASE_URL": "postgresql+psycopg://app:app@127.0.0.1:55433/app",
                "CRM_REDIS_URL": "redis://127.0.0.1:16380/0",
                "CRM_TEST_REDIS_URL": "redis://127.0.0.1:16380/0",
            },
        )
        out = proc.stdout
        failed = [ln for ln in out.splitlines() if ln.startswith("FAILED")]
        summary = [ln for ln in out.splitlines() if " passed" in ln or " failed" in ln]
        detail = "\n".join(failed[:4])
        if summary:
            detail += ("\n    " if detail else "") + summary[-1].strip()
        return proc.returncode != 0, detail
    except subprocess.TimeoutExpired:
        return True, f"⏱ 挂住超过 {TIMEOUT}s（⇒ 变异引入了死循环）⇒ 算被抓到"
    finally:
        shutil.copy2(backup.name, path)
        Path(backup.name).unlink()


def main() -> int:
    results = []
    for name, rel, old, new in MUTATIONS:
        caught, detail = run_one(name, rel, old, new)
        results.append((name, caught))
        print("=" * 78)
        print(f"$ {name}")
        print(f"  文件：{rel}")
        print(f"  ⇒ {'测试变红 ✅（有区分力）' if caught else '**照样绿 ❌（这变异测不出来）**'}")
        if detail:
            for line in detail.splitlines():
                print(f"     {line}")

    print("=" * 78)
    print("变异测试汇总")
    print("=" * 78)
    for name, ok in results:
        print(f"{'✅ 捕获' if ok else '❌ 未捕获'}  {name}")
    missed = [n for n, ok in results if not ok]
    print(f"\n共 {len(results)} 条变异，捕获 {len(results) - len(missed)} 条。")
    if missed:
        print("未捕获：")
        for n in missed:
            print("  -", n)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
