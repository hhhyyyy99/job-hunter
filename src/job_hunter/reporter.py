import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from job_hunter.config import JobHunterConfig


def build_report(
    today_data: dict[str, Any],
    health: dict[str, Any],
    config: JobHunterConfig,
) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []

    lines.append("# 求职日报")
    lines.append("")
    lines.append(f"_生成时间：{generated_at}_")
    lines.append("")

    # Health status
    lines.append("## 系统状态")
    lines.append("")
    lines.append("| 检查项 | 状态 |")
    lines.append("|--------|------|")
    lines.append(f"| Bridge | {'✅ 正常' if health.get('bridge_running') else '⚠️ 离线'} |")
    lines.append(f"| 扩展连接 | {'✅ 已连接' if health.get('extension_connected') else '⚠️ 未连接'} |")
    lines.append(f"| 登录态 | {'✅ 有效' if health.get('login_valid') else '🔴 已过期'} |")
    lines.append(f"| AI 服务 | {'✅ 可用' if health.get('ai_available') else '⚠️ 不可用'} |")
    lines.append(f"| 磁盘空间 | {'✅ 充足' if health.get('disk_ok') else '⚠️ 不足'} |")
    lines.append(f"| 写操作 | {'✅ 已启用' if health.get('write_ops_enabled') else '⚠️ 已暂停'} |")
    lines.append("")

    # Overview metrics
    lines.append("## 核心指标")
    lines.append("")
    lines.append("| 维度 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| 今日搜索新岗位 | {today_data.get('new_jobs_total', 0)} |")
    lines.append(f"| L1 过滤通过 | {today_data.get('l1_passed', 0)} |")
    lines.append(f"| AI 评分通过 (≥{config.auto_apply_threshold}) | {today_data.get('l2_passed', 0)} |")
    lines.append(f"| 今日投递 | {len(today_data.get('applied', []))} / {config.max_per_day} |")
    lines.append(f"| 今日回复 | {today_data.get('replied_count', 0)} |")
    lines.append(f"| 待跟进 | {today_data.get('follow_up_count', 0)} |")
    lines.append(f"| 面试 | {today_data.get('interview_count', 0)} |")
    lines.append("")

    # Applied jobs
    applied = today_data.get("applied", [])
    lines.append("## 今日自动投递")
    lines.append("")
    if applied:
        for job in applied:
            company = job.get("company", "-")
            title = job.get("title", "-")
            score = job.get("match_score", 0)
            salary = job.get("salary", "-")
            lines.append(f"- **{company}** · {title} · {salary} · 匹配分 {int(score)} [ ]")
    else:
        lines.append("_今日无投递_")
    lines.append("")

    # Suggested (below threshold but above suggest)
    suggested = today_data.get("suggested", [])
    if suggested:
        lines.append("## 建议投递（匹配分 50-75）")
        lines.append("")
        for job in suggested:
            company = job.get("company", "-")
            title = job.get("title", "-")
            score = job.get("match_score", 0)
            reason = job.get("gap_points", ["-"])[0] if job.get("gap_points") else "-"
            lines.append(f"- **{company}** · {title} · 匹配分 {int(score)} · {reason}")
        lines.append("")

    # Follow-up conversations
    follow_ups = today_data.get("follow_ups", [])
    if follow_ups:
        lines.append("## 待跟进")
        lines.append("")
        for item in follow_ups:
            action = item.get("action", "notify_user")
            company = item.get("company", "-")
            title = item.get("title", "-")
            last_msg = item.get("last_msg", "-")

            if action == "urgent_notify":
                lines.append(f"### 🔴 {company} · {title}")
            elif action == "auto_reply":
                draft = item.get("draft", "")
                sent = item.get("sent", False)
                status = "已发送" if sent else "发送失败"
                lines.append(f"### ✅ {company} · {title} — 自动回复 {status}")
                if draft and not sent:
                    lines.append(f"> 草稿: {draft}")
            else:
                analysis = item.get("analysis", {})
                intent = analysis.get("intent", "") if isinstance(analysis, dict) else ""
                drafts = analysis.get("drafts", []) if isinstance(analysis, dict) else []
                lines.append(f"### 🟡 {company} · {title}")
                if intent:
                    lines.append(f"  意图: {intent}")
                if drafts:
                    lines.append(f"  → 建议回复: {drafts[0].get('text', '') if isinstance(drafts, list) and drafts else ''} [ ]")

            if last_msg and last_msg != "-":
                lines.append(f"  > {last_msg[:100]}")
        lines.append("")

    # Interviews
    interviews = today_data.get("interviews", [])
    if interviews:
        lines.append("## 面试")
        lines.append("")
        for iv in interviews:
            company = iv.get("company", "-")
            title = iv.get("title", "-")
            iv_time = iv.get("interview_time", "-")
            location = iv.get("interview_location", "-")
            lines.append(f"- 🔔 **{company}** · {title} · {iv_time} · {location}")
            if iv.get("prep_material"):
                lines.append(f"  → 面试准备已生成（见附录）")
        lines.append("")

    # System health warnings
    warnings = []
    if not health.get("bridge_running"):
        warnings.append("⚠️ Bridge daemon 未运行，写操作已暂停。请启动 Bridge daemon。")
    elif not health.get("extension_connected"):
        warnings.append("⚠️ Chrome 扩展未连接，写操作已暂停。请在 Chrome 中启用 BOSS Agent Bridge 扩展。")
    if not health.get("login_valid"):
        warnings.append("🔴 BOSS 直聘登录已过期，请在 Chrome 中打开 zhipin.com 重新登录。")
    if not health.get("ai_available"):
        warnings.append("⚠️ AI 服务不可用，评分和回复功能可能受影响。请检查 boss ai config。")

    if warnings:
        lines.append("## 需要处理")
        lines.append("")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("_由 `job-hunter` 生成 · 基于 [boss-agent-cli](https://github.com/can4hou6joeng4/boss-agent-cli)_")
    lines.append("")
    lines.append("> 标记说明：`[ ]` 改为 `[x]` 表示你认为此操作不合理，系统将在下次运行时学习你的偏好。")
    lines.append("")

    return "\n".join(lines)


def write_report(md_text: str, config: JobHunterConfig) -> str:
    output_dir = Path(config.report_output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    filepath = output_dir / f"求职日报-{today}.md"
    filepath.write_text(md_text, encoding="utf-8")
    return str(filepath)
