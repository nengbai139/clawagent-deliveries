"""岗位角色与权限矩阵（S2-IAM-015）。

模块一览：
    constants.py  取值常量（角色层级 / 数据范围）
    models.py     roles / role_permissions 表
    matrix.py     读取并校验 role_matrix.yml（唯一真源）
    seed.py       幂等种子：yml → 数据库
    export.py     由 yml 生成 Markdown 矩阵表
    compare.py    yml ↔ 数据库 一致性比对
    service.py    角色读写与删除保护（内置角色删除 ⇒ 409）
    cli.py        命令行脚本的公共支撑

本包刻意不在 __init__ 里 import models（那会强制依赖 SQLAlchemy），
这样 matrix.py / export.py 可以脱离数据库单独使用。
"""
