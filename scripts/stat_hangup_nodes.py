#!/usr/bin/env python3
"""
统计脚本：按 task_id 统计一段时间内的节点挂断数量与拒识挂断数量。

口径说明：
1) 挂断节点 = qa_pairs 中最后一个有效节点（最后一个含节点键且值为 dict 的元素）
2) 节点挂断数量 = 按 (task_id, 挂断节点) 聚合的挂断次数
3) 拒识挂断数量 = 最后机器人话术包含指定关键词，且 hangup_by=2(用户挂断) 的数量
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import text

# Allow running this script directly from any working directory.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.database import close_portrait_db, get_portrait_db, init_portrait_db


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="统计节点挂断与拒识挂断数量")
    parser.add_argument("--start-date", default="2026-02-01", help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", default="2026-02-28", help="结束日期 YYYY-MM-DD，不传则同 start-date")
    parser.add_argument("--task-id", default="29e374be-3313-49ed-8de4-c41d25589e0d", help="可选：仅统计指定 task_id")
    parser.add_argument("--table-name", default="call_record_enriched", help="统计表名")
    parser.add_argument("--refuse-keyword", default="不好意思", help="拒识关键词")
    parser.add_argument(
        "--output",
        default="hangup_stats.json",
        help="可选：输出 JSON 文件路径",
    )
    return parser.parse_args()


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_qa_pairs(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        val = raw.strip()
        if not val:
            return []
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _extract_last_node_and_robot_text(qa_pairs: list[dict[str, Any]]) -> tuple[str, str]:
    '''从 qa_pairs 中提取最后一个有效节点和对应的机器人话术文本'''
    last_node = "UNKNOWN"
    last_robot_text = ""
    for item in qa_pairs:
        if not isinstance(item, dict):
            continue
        node_keys = [k for k in item.keys() if k != "tags"]
        if not node_keys:
            continue
        node = node_keys[0]
        payload = item.get(node)
        if isinstance(payload, dict):
            last_node = str(node)
            robot_text = payload.get("robot")
            if isinstance(robot_text, str):
                last_robot_text = robot_text
    # if last_node == "上门否定":
    #     logger.warning(f"{qa_pairs}")
    return last_node, last_robot_text


def _extract_prev_node(qa_pairs: list[dict[str, Any]]) -> str:
    """提取倒数第二个有效节点。"""
    nodes: list[str] = []
    for item in qa_pairs:
        if not isinstance(item, dict):
            continue
        node_keys = [k for k in item.keys() if k != "tags"]
        if not node_keys:
            continue
        node = node_keys[0]
        payload = item.get(node)
        if isinstance(payload, dict):
            nodes.append(str(node))
    if len(nodes) >= 2:
        return nodes[-2]
    return "UNKNOWN"


async def _fetch_rows(
    table_name: str,
    start_date: date,
    end_date: date,
    task_id: str | None,
) -> list[dict[str, Any]]:
    where_task = " AND task_id::text = :task_id" if task_id else ""
    sql = text(
        f"""
        SELECT callid, task_id::text AS task_id, hangup_by, qa_pairs, phone
        FROM {table_name}
        WHERE call_date >= :start_date
          AND call_date <= :end_date
          {where_task}
        """
    )
    params: dict[str, Any] = {
        "start_date": start_date,
        "end_date": end_date,
    }
    if task_id:
        params["task_id"] = task_id

    rows: list[dict[str, Any]] = []
    async for session in get_portrait_db():
        rs = await session.execute(sql, params)
        rows = [dict(r._mapping) for r in rs.fetchall()]
    return rows


def _build_stats(rows: list[dict[str, Any]], refuse_keyword: str) -> dict[str, Any]:
    node_counts: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"total": 0, "robot_hangup": 0, "user_hangup": 0}
    )
    prev_node_counts: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"total": 0, "robot_hangup": 0, "user_hangup": 0}
    )
    refuse_counts: dict[tuple[str, str], int] = defaultdict(int)
    task_totals: dict[str, int] = defaultdict(int)

    for row in rows:
        task_id = row.get("task_id") or "UNKNOWN_TASK"
        hangup_by = row.get("hangup_by")
        qa_pairs = _parse_qa_pairs(row.get("qa_pairs"))
        node, robot_text = _extract_last_node_and_robot_text(qa_pairs)
        prev_node = _extract_prev_node(qa_pairs)

        key = (task_id, node)
        node_counts[key]["total"] += 1
        if hangup_by == 1:
            node_counts[key]["robot_hangup"] += 1
        elif hangup_by == 2:
            node_counts[key]["user_hangup"] += 1

        prev_key = (task_id, prev_node)
        prev_node_counts[prev_key]["total"] += 1
        if hangup_by == 1:
            prev_node_counts[prev_key]["robot_hangup"] += 1
        elif hangup_by == 2:
            prev_node_counts[prev_key]["user_hangup"] += 1

        task_totals[task_id] += 1

        if hangup_by == 2 and refuse_keyword in (robot_text or ""):
            refuse_counts[key] += 1

    task_node_stats: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (task_id, node), v in node_counts.items():
        task_node_stats[task_id].append(
            {
                "node": node,
                "hangup_total": v["total"],
                "hangup_robot": v["robot_hangup"],
                "hangup_user": v["user_hangup"],
                "refuse_user_hangup": refuse_counts.get((task_id, node), 0),
            }
        )

    for task_id in task_node_stats:
        task_node_stats[task_id].sort(key=lambda x: x["hangup_total"], reverse=True)

    task_node_stats_prev: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (task_id, node), v in prev_node_counts.items():
        task_node_stats_prev[task_id].append(
            {
                "node": node,
                "hangup_total": v["total"],
                "hangup_robot": v["robot_hangup"],
                "hangup_user": v["user_hangup"],
            }
        )

    for task_id in task_node_stats_prev:
        task_node_stats_prev[task_id].sort(key=lambda x: x["hangup_total"], reverse=True)

    return {
        "summary": {
            "record_count": len(rows),
            "task_count": len(task_node_stats),
            "refuse_keyword": refuse_keyword,
        },
        "task_totals": dict(task_totals),
        "task_node_stats": dict(task_node_stats),
        "task_node_stats_倒数第二个": dict(task_node_stats_prev),
    }


def _print_stats(stats: dict[str, Any]) -> None:
    summary = stats["summary"]
    print(f"记录数: {summary['record_count']}")
    print(f"任务数: {summary['task_count']}")
    print(f"拒识关键词: {summary['refuse_keyword']}")
    print("-" * 80)

    task_node_stats: dict[str, list[dict[str, Any]]] = stats["task_node_stats"]
    if not task_node_stats:
        print("无统计结果")
        return

    for task_id, rows in task_node_stats.items():
        print(f"task_id={task_id} | total={stats['task_totals'].get(task_id, 0)}")
        print("node\thangup_total\thangup_robot\thangup_user\trefuse_user_hangup")
        for r in rows:
            print(
                f"{r['node']}\t{r['hangup_total']}\t{r['hangup_robot']}\t"
                f"{r['hangup_user']}\t{r['refuse_user_hangup']}"
            )
        print("-" * 80)

        prev_rows = stats.get("task_node_stats_倒数第二个", {}).get(task_id, [])
        print("倒数第二个node\thangup_total\thangup_robot\thangup_user")
        for r in prev_rows:
            print(
                f"{r['node']}\t{r['hangup_total']}\t{r['hangup_robot']}\t{r['hangup_user']}"
            )
        print("-" * 80)


async def main() -> None:
    args = parse_args()
    start_date = _parse_date(args.start_date)
    end_date = _parse_date(args.end_date) if args.end_date else start_date
    if end_date < start_date:
        raise ValueError("end-date 不能早于 start-date")

    await init_portrait_db()
    try:
        rows = await _fetch_rows(args.table_name, start_date, end_date, args.task_id)
        stats = _build_stats(rows, args.refuse_keyword)
        _print_stats(stats)

        if args.output:
            out = Path(args.output)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(f"统计结果已输出: {out}")
    finally:
        await close_portrait_db()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
