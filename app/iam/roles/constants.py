"""角色与权限矩阵的取值常量（不依赖 SQLAlchemy，便于脚本单独使用）。"""

from __future__ import annotations

# 角色层级：site（本会所岗位）/ org（组织级岗位）
ROLE_LEVEL_SITE = "site"
ROLE_LEVEL_ORG = "org"
ROLE_LEVELS = (ROLE_LEVEL_SITE, ROLE_LEVEL_ORG)

# 数据范围：self（本人）/ site（本会所）/ org（全组织）
DATA_SCOPE_SELF = "self"
DATA_SCOPE_SITE = "site"
DATA_SCOPE_ORG = "org"
DATA_SCOPES = (DATA_SCOPE_SELF, DATA_SCOPE_SITE, DATA_SCOPE_ORG)
