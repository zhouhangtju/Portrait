#!/usr/bin/env python3
"""
独立脚本：从原始 MySQL 查询通话记录，调详情接口解析后写入画像库。

流程：
1. 按日期范围扫描 autodialer_call_record_YYYY_MM 分表
2. 调用 /agent-api/user/{user_id}/task/{task_id}/detail/{record_id}
3. 解析 qa_pairs / voice_urls
4. upsert 到 call_record_enriched（按 callid 冲突更新）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import date, datetime
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from src.core.config import settings
from src.core.database import (
    close_portrait_db,
    close_source_db,
    get_portrait_db,
    get_source_db,
    init_portrait_db,
    init_source_db,
    is_source_db_available,
)
from src.models.portrait.call_enriched import CallRecordEnriched
from src.services.etl_service import etl_service
from src.utils.table_utils import check_table_exists_sql, get_tables_for_period


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从源库拉取通话详情并入库")
    parser.add_argument("--start-date", type=str, required=True, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, default=None, help="结束日期 YYYY-MM-DD，不传则同 start-date")
    parser.add_argument("--task-id", type=str, default=None, help="可选：按 task_id 过滤")
    parser.add_argument("--call-status", type=str, default="connected", choices=["all", "connected"], help="是否仅处理接通")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少条（0=不限制）")
    parser.add_argument("--max-concurrency", type=int, default=10, help="接口并发")
    parser.add_argument("--http-timeout", type=int, default=15, help="接口超时秒数")
    parser.add_argument("--write-batch-size", type=int, default=200, help="写入画像库批次")
    parser.add_argument("--api-base-url", type=str, default="", help="接口基础地址，默认读取 AGENT_API_BASE_URL")
    parser.add_argument("--api-token", type=str, default="", help="接口 token，默认读取 AGENT_API_TOKEN")
    parser.add_argument("--dry-run", action="store_true", help="仅拉取解析，不写入画像库")
    return parser.parse_args()


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


async def _get_existing_tables(start_date: date, end_date: date) -> list[str]:
    candidates = get_tables_for_period(start_date, end_date, table_type="call_record")
    exists: list[str] = []
    async for session in get_source_db():
        for table_name in candidates:
            rs = await session.execute(text(check_table_exists_sql(table_name)))
            if (rs.scalar() or 0) > 0:
                exists.append(table_name)
            else:
                logger.warning(f"分表不存在，跳过: {table_name}")
    return exists


async def _fetch_base_rows(
    table_name: str,
    start_date: date,
    end_date: date,
    task_id: str | None,
    call_status: str,
) -> list[dict[str, Any]]:
    where_task = " AND cr.task_id = :task_id" if task_id else ""
    where_connected = " AND cr.bill > 0" if call_status == "connected" else ""

    sql = text(
        f"""
        SELECT
            cr.id AS record_id,
            cr.callid AS callid,
            cr.task_id AS task_id,
            cr.user_id AS user_id,
            cr.callee AS phone,
            DATE(cr.calldate) AS call_date,
            cr.duration AS duration,
            cr.bill AS bill,
            cr.rounds AS rounds,
            cr.level_name AS level_name,
            cr.intention_results AS intention_result,
            cr.hangup_disposition AS hangup_by,
            CASE WHEN cr.bill > 0 THEN 'connected' ELSE 'failed' END AS call_status
        FROM {table_name} cr
        WHERE DATE(cr.calldate) >= :start_date
          AND DATE(cr.calldate) <= :end_date
          {where_task}
          {where_connected}
        """
    )

    params: dict[str, Any] = {"start_date": start_date, "end_date": end_date}
    if task_id:
        params["task_id"] = task_id

    rows_data: list[dict[str, Any]] = []
    async for session in get_source_db():
        rs = await session.execute(sql, params)
        for row in rs.fetchall():
            try:
                task_uuid = uuid.UUID(str(row.task_id))
            except Exception:
                logger.warning(f"跳过 task_id 非法记录 callid={row.callid}, task_id={row.task_id}")
                continue

            intention_result = row.intention_result
            if intention_result is not None:
                intention_result = str(intention_result) if intention_result != 0 else None

            rows_data.append(
                {
                    "record_id": str(row.record_id),
                    "callid": str(row.callid),
                    "task_id": str(task_uuid),
                    "task_id_uuid": task_uuid,
                    "user_id": str(row.user_id),
                    "phone": row.phone,
                    "call_date": row.call_date,
                    "duration": row.duration or 0,
                    "bill": row.bill or 0,
                    "rounds": row.rounds or 0,
                    "level_name": row.level_name,
                    "intention_result": intention_result,
                    "hangup_by": row.hangup_by,
                    "call_status": row.call_status,
                }
            )
    return rows_data


async def _fetch_detail_json(
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    user_id: str,
    task_id: str,
    record_id: str,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/agent-api/user/{user_id}/task/{task_id}/detail/{record_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    resp = await client.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


async def _parse_one(
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    base_row: dict[str, Any],
) -> dict[str, Any]:
    async with sem:
        try:
            detail_json = await _fetch_detail_json(
                client=client,
                base_url=base_url,
                token=token,
                user_id=base_row["user_id"],
                task_id=base_row["task_id"],
                record_id=base_row["record_id"],
            )
            qa_pairs = await etl_service.extract_qa_pairs(detail_json)
            voice_urls = await etl_service.extract_voice_urls(detail_json)
            return {
                **base_row,
                "qa_pairs": qa_pairs,
                "voice_urls": voice_urls,
                "parse_status": "success",
                "parse_error": None,
            }
        except Exception as e:
            logger.error(f"解析失败 callid={base_row.get('callid')}: {e}")
            return {
                **base_row,
                "qa_pairs": [],
                "voice_urls": [],
                "parse_status": "failed",
                "parse_error": str(e),
            }


async def _upsert_portrait(rows: list[dict[str, Any]], batch_size: int) -> int:
    if not rows:
        return 0

    payload: list[dict[str, Any]] = []
    for r in rows:
        payload.append(
            {
                "callid": r["callid"],
                "task_id": r["task_id_uuid"],
                "user_id": r["user_id"],
                "phone": r["phone"],
                "call_date": r["call_date"],
                "duration": r["duration"],
                "bill": r["bill"],
                "rounds": r["rounds"],
                "level_name": r["level_name"],
                "intention_result": r["intention_result"],
                "hangup_by": r["hangup_by"],
                "call_status": r["call_status"],
                "qa_pairs": json.dumps(r.get("qa_pairs", []), ensure_ascii=False),
            }
        )

    written = 0
    async for session in get_portrait_db():
        for i in range(0, len(payload), batch_size):
            batch = payload[i : i + batch_size]
            stmt = insert(CallRecordEnriched).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=["callid"],
                set_={
                    "task_id": stmt.excluded.task_id,
                    "user_id": stmt.excluded.user_id,
                    "phone": stmt.excluded.phone,
                    "call_date": stmt.excluded.call_date,
                    "duration": stmt.excluded.duration,
                    "bill": stmt.excluded.bill,
                    "rounds": stmt.excluded.rounds,
                    "level_name": stmt.excluded.level_name,
                    "intention_result": stmt.excluded.intention_result,
                    "hangup_by": stmt.excluded.hangup_by,
                    "call_status": stmt.excluded.call_status,
                    "qa_pairs": stmt.excluded.qa_pairs,
                    "updated_at": datetime.now(),
                },
            )
            await session.execute(stmt)
            written += len(batch)
    return written


async def main() -> None:
    args = parse_args()
    start_date = _parse_date(args.start_date)
    end_date = _parse_date(args.end_date) if args.end_date else start_date
    if end_date < start_date:
        raise ValueError("end-date 不能早于 start-date")

    base_url = (args.api_base_url or settings.agent_api_base_url or "").strip()
    token = (args.api_token or settings.agent_api_token or "").strip()
    if not base_url or not token:
        raise RuntimeError("缺少接口配置：请设置 --api-base-url/--api-token 或 .env 里的 AGENT_API_*")

    await init_source_db()
    if not is_source_db_available():
        raise RuntimeError("MySQL 源数据库不可用")
    if not args.dry_run:
        await init_portrait_db()

    try:
        tables = await _get_existing_tables(start_date, end_date)
        if not tables:
            logger.warning("日期范围内未找到通话分表")
            return

        base_rows: list[dict[str, Any]] = []
        for table_name in tables:
            logger.info(f"读取分表: {table_name}")
            base_rows.extend(
                await _fetch_base_rows(
                    table_name=table_name,
                    start_date=start_date,
                    end_date=end_date,
                    task_id=args.task_id,
                    call_status=args.call_status,
                )
            )

        dedup = {r["callid"]: r for r in base_rows}
        rows = list(dedup.values())
        if args.limit and args.limit > 0:
            rows = rows[: args.limit]

        if not rows:
            logger.info("没有符合条件的通话记录")
            return

        logger.info(f"待解析记录数: {len(rows)}")
        sem = asyncio.Semaphore(args.max_concurrency)
        timeout = httpx.Timeout(args.http_timeout)
        async with httpx.AsyncClient(timeout=timeout) as client:
            parsed = await asyncio.gather(
                *[
                    _parse_one(
                        sem=sem,
                        client=client,
                        base_url=base_url,
                        token=token,
                        base_row=row,
                    )
                    for row in rows
                ]
            )

        success_rows = [r for r in parsed if r.get("parse_status") == "success"]
        failed = len(parsed) - len(success_rows)
        logger.info(f"解析完成 success={len(success_rows)}, failed={failed}")

        if args.dry_run:
            return

        written = await _upsert_portrait(success_rows, args.write_batch_size)
        logger.info(f"入库完成，写入/更新 {written} 条")
    finally:
        if not args.dry_run:
            await close_portrait_db()
        await close_source_db()


if __name__ == "__main__":
    asyncio.run(main())
