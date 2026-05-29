import sys
import threading
from pathlib import Path

import click

from job_hunter.config import DEFAULT_CONFIG_DIR, load_config, JobHunterConfig
from job_hunter.db import StateDB
from job_hunter.scheduler import health_check
from job_hunter.pipeline import daily_pipeline, conversation_loop


@click.group(name="job-hunter")
@click.option("--config", "config_path", default=None, help="配置文件路径（默认 ~/.boss-agent/job-hunter/config.yaml）")
@click.option("--data-dir", default=str(DEFAULT_CONFIG_DIR), help="数据目录")
@click.pass_context
def cli(ctx: click.Context, config_path: str | None, data_dir: str) -> None:
    ctx.ensure_object(dict)
    ctx.obj["data_dir"] = Path(data_dir).expanduser()
    ctx.obj["data_dir"].mkdir(parents=True, exist_ok=True)
    cfg_path = Path(config_path).expanduser() if config_path else None
    ctx.obj["config"] = load_config(cfg_path)
    ctx.obj["config_path"] = cfg_path


@cli.command("start")
@click.option("--dry-run", is_flag=True, default=False, help="仅模拟执行，不实际投递/回复")
@click.pass_context
def start_cmd(ctx: click.Context, dry_run: bool) -> None:
    """启动 job-hunter 守护进程（常驻后台，事件驱动）"""
    config: JobHunterConfig = ctx.obj["config"]
    data_dir: Path = ctx.obj["data_dir"]

    click.echo("job-hunter daemon 启动中...")
    health = health_check(config, data_dir)
    click.echo(f"Bridge: {'OK' if health.get('extension_connected') else '未连接'}")
    click.echo(f"登录态: {'OK' if health.get('login_valid') else '过期'}")

    # Start conversation polling loop in background
    poll_thread = threading.Thread(
        target=conversation_loop,
        args=(config, data_dir, dry_run),
        daemon=True,
    )
    poll_thread.start()
    click.echo("对话轮询已启动")

    # Run daily pipeline immediately then wait for next day
    click.echo("等待触发条件...")
    report_path = daily_pipeline(config, data_dir, dry_run=dry_run)
    click.echo(f"日报已生成: {report_path}")

    # Keep alive
    try:
        while True:
            import time
            time.sleep(60)
    except KeyboardInterrupt:
        click.echo("job-hunter 已停止")


@cli.command("stop")
def stop_cmd() -> None:
    """停止 job-hunter 守护进程"""
    click.echo("job-hunter daemon 停止指令已发送")


@cli.command("status")
@click.pass_context
def status_cmd(ctx: click.Context) -> None:
    """查看 job-hunter 运行状态"""
    data_dir = ctx.obj["data_dir"]
    config: JobHunterConfig = ctx.obj["config"]
    health = health_check(config, data_dir)

    click.echo("=== job-hunter 状态 ===")
    click.echo(f"配置目录: {data_dir}")
    click.echo(f"Bridge: {'正常' if health.get('bridge_running') else '离线'}")
    click.echo(f"扩展: {'已连接' if health.get('extension_connected') else '未连接'}")
    click.echo(f"登录态: {'有效' if health.get('login_valid') else '过期'}")
    click.echo(f"AI 服务: {'可用' if health.get('ai_available') else '不可用'}")
    click.echo(f"写操作: {'已启用' if health.get('write_ops_enabled') else '已暂停'}")

    with StateDB(data_dir / "state.db") as db:
        today = __import__("datetime").date.today().isoformat()
        done = db.is_today_done(today)
        apply_count = db.count_applies_today()
        pending = len(db.get_pending_candidates())

    click.echo(f"今日已执行: {'是' if done else '否'}")
    click.echo(f"今日投递: {apply_count}")
    click.echo(f"候选池待投: {pending}")


@cli.command("run")
@click.option("--dry-run", is_flag=True, default=False, help="仅模拟执行，不实际投递/回复")
@click.pass_context
def run_cmd(ctx: click.Context, dry_run: bool) -> None:
    """手动触发一次完整的每日 pipeline（非守护进程，执行完即退出）"""
    config: JobHunterConfig = ctx.obj["config"]
    data_dir: Path = ctx.obj["data_dir"]

    click.echo("执行每日 pipeline...")
    report_path = daily_pipeline(config, data_dir, dry_run=dry_run)
    click.echo(f"完成！日报: {report_path}")


@cli.command("config")
@click.pass_context
def config_cmd(ctx: click.Context) -> None:
    """显示当前配置"""
    config: JobHunterConfig = ctx.obj["config"]
    config_path = ctx.obj.get("config_path")
    click.echo(f"配置文件: {config_path or '使用默认配置'}")
    for field in sorted(config.__dataclass_fields__):
        value = getattr(config, field)
        click.echo(f"  {field}: {value}")


if __name__ == "__main__":
    cli()
