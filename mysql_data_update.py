# update_visit_reason.py
import asyncio
import pandas as pd
from sqlalchemy import text
from src.core.database import init_portrait_db, close_portrait_db, get_portrait_db  # 复用你的模块

async def update_visit_reasons():
    # 初始化数据库连接（对应你的 init_portrait_db）
    await init_portrait_db()

    try:
        # 读取 Excel
        df = pd.read_excel("call_record_enriched_with_model_res.xlsx")
        filtered = df[df['visit_needed'] == 'yes'][['id', 'visit_reason']]

        if filtered.empty:
            print("✅ 没有需要更新的记录。")
            return

        updates = []
        for _, row in filtered.iterrows():
            record_id = str(row['id']).strip()
            reason = str(row['visit_reason']) if pd.notna(row['visit_reason']) else ''
            updates.append((reason, record_id))

        # 使用你项目中的 get_portrait_db 获取会话
        async for session in get_portrait_db():
            try:
                for reason, record_id in updates:
                    await session.execute(
                        text("""
                            UPDATE call_record_enriched
                            SET visit_reason = :reason
                            WHERE id = :record_id
                        """),
                        {"reason": reason, "record_id": record_id}
                    )
                await session.commit()
                print(f"✅ 成功更新 {len(updates)} 条记录。")
            except Exception as e:
                await session.rollback()
                print("❌ 更新失败:", e)
                raise
    finally:
        await close_portrait_db()

if __name__ == "__main__":
    asyncio.run(update_visit_reasons())