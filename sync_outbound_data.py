import asyncio
from typing import Any, List, Dict
from urllib.parse import quote_plus
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

# =================配置区域=================
DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "123456",
    "target_db": "outbound",
    "source_dbs": ["mysql", "online_mark"],
    "table_name": "autodialer_call_record_2025_11"
}


# =========================================

class RawSyncService:
    def __init__(self):
        self.target_engine = None
        self.source_engines = {}

    async def init_engines(self):
        """初始化数据库引擎"""
        password_encoded = quote_plus(DB_CONFIG["password"])

        # 目标库
        target_dsn = (
            f"mysql+aiomysql://{DB_CONFIG['user']}:{password_encoded}"
            f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['target_db']}"
        )
        self.target_engine = create_async_engine(target_dsn, echo=False, pool_pre_ping=True)

        # 源库
        for db_name in DB_CONFIG["source_dbs"]:
            source_dsn = (
                f"mysql+aiomysql://{DB_CONFIG['user']}:{password_encoded}"
                f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{db_name}"
            )
            self.source_engines[db_name] = create_async_engine(source_dsn, echo=False, pool_pre_ping=True)

    async def _fetch_source_records(self, session: AsyncSession, table_name: str) -> List[Dict[str, Any]]:
        """
        原样读取数据，不做任何类型转换或 UUID 处理
        直接将行数据转换为字典列表
        """
        sql = text(f"SELECT * FROM {table_name}")
        records = []

        result = await session.execute(sql)
        rows = result.fetchall()
        columns = result.keys()

        # 简单映射：列名 -> 值 (保持数据库原始类型)
        for row in rows:
            record = {col: row[i] for i, col in enumerate(columns)}
            records.append(record)

        return records

    async def _upsert_records(self, session: AsyncSession, records: List[Dict[str, Any]], table_name: str):
        """
        批量插入/更新数据
        使用 MySQL 语法: INSERT ... ON DUPLICATE KEY UPDATE
        """
        if not records:
            return

        columns = list(records[0].keys())
        col_names = ", ".join([f"`{c}`" for c in columns])
        placeholders = ", ".join([f":{c}" for c in columns])

        # 构造更新子句：如果主键冲突，则更新所有字段为传入的值
        update_clause = ", ".join([f"`{c}`=VALUES(`{c}`)" for c in columns])

        insert_sql = text(f"""
            INSERT INTO {table_name} ({col_names}) 
            VALUES ({placeholders})
            ON DUPLICATE KEY UPDATE {update_clause}
        """)

        # 分批提交 (每批 1000 条)
        batch_size = 1000
        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            await session.execute(insert_sql, batch)

    async def sync_database(self, source_db_name: str):
        """执行单个库的同步"""
        logger.info(f">>> 开始同步: {source_db_name} -> {DB_CONFIG['target_db']}")

        source_engine = self.source_engines.get(source_db_name)
        if not source_engine:
            return

        source_session_maker = async_sessionmaker(bind=source_engine, class_=AsyncSession)
        target_session_maker = async_sessionmaker(bind=self.target_engine, class_=AsyncSession)
        table_name = DB_CONFIG["table_name"]

        try:
            # 1. 读取 (不做处理)
            async with source_session_maker() as source_session:
                records = await self._fetch_source_records(source_session, table_name)

            if not records:
                logger.info(f"[{source_db_name}] 无数据，跳过。")
                return

            logger.info(f"[{source_db_name}] 读取到 {len(records)} 条原始记录。")

            # 2. 写入
            async with target_session_maker() as target_session:
                await self._upsert_records(target_session, records, table_name)
                await target_session.commit()

            logger.success(f"[{source_db_name}] 同步完成。")

        except Exception as e:
            logger.error(f"[{source_db_name}] 同步失败: {e}")

    async def run(self):
        await self.init_engines()
        for db in DB_CONFIG["source_dbs"]:
            await self.sync_database(db)

        # 关闭连接
        await self.target_engine.dispose()
        for eng in self.source_engines.values():
            await eng.dispose()
        logger.info("=== 全部任务结束 ===")


async def main():
    service = RawSyncService()
    await service.run()


if __name__ == "__main__":
    asyncio.run(main())