"""报备方页面（工单原文：「接口文档与**报备方页面**都写明这一点」）。

⚠️ **为什么有这一层**：工单要求「争议只受理系统判断错误类原因……**接口文档
与报备方页面都写明这一点**」⇒ 两处都要写：
* 接口文档 ⇒ `app/api/routes.py` 里的 OpenAPI `description`；
* 报备方页面 ⇒ 本模块。

⚠️ **这里的文案是「给人看的规则」**，与代码里的白名单
（`app.services.dispute.ALLOWED_REASON_CODES`）**必须一致** ⇒
⇒ 下面**从白名单生成**，不手写一份 ⇒ 两边不可能漂移。

⚠️ **不受理的理由也要写出来**（并说明原因），否则报备方会反复提交
被拒的理由（「我之前线下就见过」是**很常见**的误提）。
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.services.dispute import (
    ALLOWED_REASON_CODES,
    MAX_ATTACHMENTS,
    REJECTED_REASON_HINTS,
)

router = APIRouter()

#: 受理理由的**人话说明**（键是 `reason_code`）。
REASON_LABELS: dict[str, str] = {
    "normalization_false_duplicate": "系统把这条归一化后误判成了重复",
    "existing_customer_data_error": "系统里存量客户信息有误",
    "wrong_attribution": "归属判给了错误的人",
    "other_system_error": "其它系统判断错误",
}


def _reason_rows() -> list[tuple[str, str]]:
    """受理理由表（**从白名单生成** ⇒ 不会与代码漂移）。"""
    return [(code, REASON_LABELS.get(code, code)) for code in sorted(ALLOWED_REASON_CODES)]


@router.get("/ref/report/{report_id}/dispute", response_class=HTMLResponse)
def dispute_form(report_id: str) -> HTMLResponse:
    """报备方提交争议的页面（含**受理范围**说明）。"""
    # ⚠️ **受理理由表从白名单生成**（不手写一份）⇒ 页面与代码**不可能漂移**。
    rows = "\n".join(
        f"      <tr><td><code>{code}</code></td><td>{label}</td></tr>"
        for code, label in _reason_rows()
    )
    rejected = "\n".join(
        f"      <li><code>{code}</code> —— {hint}</li>"
        for code, hint in sorted(REJECTED_REASON_HINTS.items())
    )
    return HTMLResponse(
        f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>对报备 {report_id} 提出异议</title>
<style>
  body {{ font-family: system-ui, -apple-system, "PingFang SC", sans-serif;
         max-width: 760px; margin: 40px auto; padding: 0 20px; line-height: 1.7;
         color: #1a1a1a; }}
  h1 {{ font-size: 20px; }}
  .notice {{ border-left: 4px solid #d93025; background: #fdf2f2;
            padding: 12px 16px; margin: 16px 0; border-radius: 4px; }}
  .ok {{ border-left-color: #1a7f37; background: #f1f8f3; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
  th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
  th {{ background: #f6f8fa; }}
  code {{ background: #f3f4f6; padding: 1px 5px; border-radius: 3px; font-size: 13px; }}
  form {{ margin-top: 24px; }}
  label {{ display: block; margin: 14px 0 6px; font-weight: 600; }}
  select, textarea {{ width: 100%; padding: 8px; box-sizing: border-box;
                      border: 1px solid #ccc; border-radius: 4px; font: inherit; }}
  textarea {{ min-height: 120px; }}
  button {{ margin-top: 16px; padding: 10px 20px; border: 0; border-radius: 4px;
            background: #1f6feb; color: #fff; font: inherit; cursor: pointer; }}
  .hint {{ color: #57606a; font-size: 13px; }}
</style>
</head>
<body>
<h1>对报备 {report_id} 提出异议</h1>

<div class="notice ok">
  <strong>什么可以提？</strong>
  <p>只有<strong>系统判断错误</strong>类的异议会被受理：</p>
  <table>
    <tr><th>原因</th><th>说明</th></tr>
{rows}
  </table>
</div>

<div class="notice">
  <strong>什么<em>不</em>可以提？</strong>
  <p>凡是<strong>与首次报备规则冲突</strong>的理由都不受理，例如：</p>
  <ul>
{rejected}
  </ul>
  <p class="hint">这些情况按<strong>首次报备</strong>规则判定归属，
  线下接触过不改变结果，因此无法通过异议改变。</p>
</div>

<form method="post" action="/api/ref/reports/{report_id}/disputes">
  <label for="reason_code">异议原因</label>
  <select id="reason_code" name="reason_code" required>
    {"".join(f'<option value="{code}">{label}</option>' for code, label in _reason_rows())}
  </select>

  <label for="reason_text">说明</label>
  <textarea id="reason_text" name="reason_text" required
            placeholder="请说明系统的判断错在哪里"></textarea>

  <label for="attachments">证据附件（最多 {MAX_ATTACHMENTS} 个）</label>
  <input id="attachments" name="attachments" type="file" multiple>
  <p class="hint">最多 {MAX_ATTACHMENTS} 个文件。</p>

  <button type="submit">提交异议</button>
</form>
</body>
</html>"""
    )
