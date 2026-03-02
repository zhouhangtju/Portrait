
import pandas as pd
import json
import asyncio
from src.services.rule_engine_service import rule_engine


async def main():
    # 1. 初始化服务
    service = rule_engine

    # 2. 读取 CSV 文件
    input_file = 'call_record_enriched.csv'
    output_file = 'call_record_enriched_with_model_res.csv'

    print(f"正在读取文件: {input_file} ...")
    try:
        df = pd.read_csv(input_file)
    except FileNotFoundError:
        print(f"错误: 找不到文件 {input_file}")
        return

    # 3. 筛选 visit_needed 为 'yes' 的行
    # 确保列存在
    if 'visit_needed' not in df.columns or 'qa_pairs' not in df.columns:
        print("错误: CSV 文件中缺少 'visit_needed' 或 'qa_pairs' 列")
        return

    # 筛选出 visit_needed 为 'yes' 的行 (注意处理可能的大小写或空格问题)
    mask = df['visit_needed'].astype(str).str.strip().str.lower() == 'yes'
    filtered_df = df[mask].copy()

    if filtered_df.empty:
        print("未找到 visit_needed 为 'yes' 的记录，无需处理。")
        # 即使没有数据，也建议创建一个空的结果列并保存，以保持格式一致
        df['model_res'] = None
        df.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"已生成空结果文件: {output_file}")
        return

    print(f"找到 {len(filtered_df)} 条需要处理的记录。")

    # 4. 准备存储结果的列表 (初始化为 None，保持与原表行数一致)
    model_results = [None] * len(df)

    # 获取需要处理的行的原始索引
    target_indices = filtered_df.index.tolist()

    print("开始调用模型进行处理...")

    # 5. 遍历并调用 get_visit_and_reasoin
    # 使用 tqdm 可以显示进度条 (如果安装了 tqdm: pip install tqdm)
    try:
        from tqdm import tqdm
        iterator = tqdm(target_indices, desc="Processing")
    except ImportError:
        iterator = target_indices

    for idx in iterator:
        qa_pairs_str = df.at[idx, 'qa_pairs']

        try:
            # 解析 JSON 字符串
            if isinstance(qa_pairs_str, str):
                qa_pairs = json.loads(qa_pairs_str)
            elif isinstance(qa_pairs_str, list):
                qa_pairs = qa_pairs_str
            else:
                # 如果是空值或其他类型，跳过
                continue

            # 调用方法
            # get_visit_and_reasoin 返回的是 (visit_needed, visit_reason) 元组
            visit_needed, visit_reason = await service.get_visit_and_reasoin(qa_pairs)

            # 将结果封装为字典或字符串存入
            model_results[idx] = {
                "visit_needed": visit_needed,
                "visit_reason": visit_reason
            }

        except json.JSONDecodeError:
            print(f"警告: 索引 {idx} 的 qa_pairs 不是有效的 JSON 格式。")
            model_results[idx] = {"error": "Invalid JSON"}
        except Exception as e:
            print(f"错误: 处理索引 {idx} 时发生异常: {e}")
            model_results[idx] = {"error": str(e)}

    # 6. 将结果写入新列
    df['model_res'] = model_results

    # 7. 保存到新文件
    # encoding='utf-8-sig' 防止 Excel 打开中文乱码
    df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"处理完成！结果已保存至: {output_file}")


if __name__ == "__main__":
    # 运行异步主函数
    asyncio.run(main())