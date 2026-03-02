import pandas as pd
import requests
import json
import time
from typing import List, Dict, Any
import traceback


class AgentDetailFetcher:
    def __init__(self):
        # 固定的参数
        self.base_url = "http://188.107.245.58:19999"
        self.token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJhdWQiOiIxIiwianRpIjoiZDE5NGUyMDhkNmZjZjFiYTIxYjYwZGQ2NWQ2ZTU2ODlkYzFkOTAxMzk5ZTg3ZWJiZGVlYWFmNGFhNDA0YzVlMTllZDQwODc5ZmIwNzc2NWQiLCJpYXQiOjE3NTgzNjAyMzMsIm5iZiI6MTc1ODM2MDIzMywiZXhwIjoxNzg5ODk2MjMzLCJzdWIiOiI5YWEyYzcyMi0xMmJhLTRkOWMtODA1Ni03NTc0NjFjZGVkNWUiLCJzY29wZXMiOltdfQ.tQAr3M1WgUv-YbgFZuNSiMQI5j5Mlw5vw3s7Pcwh_XRo-n1UE08AaHEIHCjHxKAcy1oYGzPrEkp8W0dP9oh_acxtoAw-7_6NXintBSrCF8tESpDvBF2Sr1yxHIVmOdXQkAbGvbnGnTwKedNq0jUqqumTjABj1odi1WoX1_KAQ8hs7RSpYvXogk9D46tRlgrGRQS7JdbrmhHy-FvYrhG4kDM2BlHlQ-zH5suOGE6X_yewi0ENvvq1AQkSclApB4QsyeUpAn-l2LsM4QaSRg_wYDsnzeJkEKfKQMDEQIOudYP1jPjzwVgQBRMi_SBKRojv8KruuXl-JXcvVse_HXiM9yw_Kl-9vEnWL-o-eugyFV35CoSU7svvc2YFSL1JCCSD3GvitutchrorxqsYrPSF6Wgud8pGFyxICI61LmiWjLEs0xriXcvUA1Cr7o_pzj--fZFq4LvBM7XUNL6O6wW585rdLhryjunpjboQWzIn7-NzZ8vk-TObx1Pm4c75ENm0wAh7pHDz8lAx4rFU3iPBnW5dDH4N36YbQT2zXooiAmNxzJ6IXFvCWxX6D_ViRF6iHrFyl7jNNwYQcpyX_HjlAzNwJEGCTuQs9JEYBUgb0M4wsR-oIAvUCM6fndEOk2H3xITu1sfAMKGWBnKtHqNPoEwklwHTDoqY24DFkYZhhuA"
        self.user_id = "3ab14961-af35-4e89-8406-e3f89b92271a"
        self.task_id = "eca85f1e-3558-40ec-8140-79f75f36eb57"

        # 需要从Excel读取的列名
        self.excel_file = "zjyd01_台州-装机单竣工回访_通话记录_202601191853_zjyd01.xlsx"
        self.record_id_column = "通话ID"

    def fetch_agent_detail_json_sync(
            self,
            record_id: str,
            timeout_s: int = 10
    ) -> dict:
        """同步调用 ASR 明细接口并返回 JSON。"""
        url = f"{self.base_url}/agent-api/user/{self.user_id}/task/{self.task_id}/detail/{record_id}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

        try:
            resp = requests.get(url, headers=headers, timeout=timeout_s)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Agent API 请求失败 status={resp.status_code}, body={resp.text[:500]}"
                )
            return resp.json()
        except requests.exceptions.Timeout:
            raise RuntimeError(f"请求超时 (timeout={timeout_s}s)")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"请求异常: {str(e)}")

    def extract_qa_pairs(self, data):
        """
        从通话记录中提取QA对

        参数:
            data: 原始JSON数据

        返回:
            QA对列表
        """
        records = data['data']['records']
        qa_pairs = []
        current_robot_question = None
        current_node = None

        # for record in records:
        for idx, record in enumerate(records):
            notify = record.get('notify')

            # 处理机器人发言
            # 1. notify == "enter" 时，机器人开场
            if notify == 'enter':
                robot_text = ""
                node_name = record.get('answer_text', '')

                # 从 contents 中提取文本
                if record.get('contents'):
                    robot_text = ' '.join([c['translate_text'] for c in record['contents']])
                elif record.get('answer_content'):
                    content = record['answer_content']
                    lines = content.split('\n')
                    robot_text = '\n'.join([line for line in lines if not line.strip().endswith('秒')])

                # 清理文本
                robot_text = robot_text.strip()
                if ':' in robot_text:
                    parts = robot_text.split(':', 1)
                    if parts[0] in ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q6', 'Q7', 'Q1-A', 'Q1-default']:
                        robot_text = parts[1].strip()

                current_robot_question = robot_text
                current_node = node_name

            # 2. notify == "asrmessage_notify" 时，可能包含用户回答和机器人新问题
            elif notify == 'asrmessage_notify':
                # 先处理用户回答（如果存在）
                if record.get('question'):
                    user_answer = record['question'].strip()

                    # 提取tags
                    tags_list = []
                    if record.get('tags'):
                        tags_list = [tag['name'] for tag in record['tags']]
                    tags_str = ','.join(tags_list) if tags_list else ''

                    # 关键：检查 answer_content 是否为 null
                    # 如果为 null，说明用户继续说话，需要合并到上一个QA对
                    if record.get('answer_text') is None:
                        # 合并逻辑：找到最后一个相同节点的QA对，合并用户回答
                        if qa_pairs and current_node:
                            last_qa = qa_pairs[-1]
                            # 检查最后一个QA对是否是当前节点
                            if current_node in last_qa:
                                # 合并用户回答
                                last_qa[current_node]['custom'] += ',' + user_answer
                                # 更新tags（如果新的有tags）
                                if tags_str:
                                    last_qa['tags'] = tags_str
                            else:
                                # 如果节点不同，创建新QA对
                                if current_robot_question:
                                    qa_pairs.append({
                                        current_node: {
                                            "robot": current_robot_question,
                                            "custom": user_answer
                                        },
                                        "tags": tags_str
                                    })
                    else:
                        # answer_content 不为 null，创建新的QA对
                        if current_robot_question and current_node:
                            if len(qa_pairs) <= 0:
                                qa_pairs.append({
                                    current_node: {
                                        "robot": current_robot_question,
                                        "custom": user_answer
                                    },
                                    "tags": tags_str
                                })
                            else:
                                last_qa = qa_pairs[-1]
                                # 检查最后一个QA对是否是当前节点
                                if current_node in last_qa:
                                    # 合并用户回答
                                    last_qa[current_node]['custom'] += ',' + user_answer
                                    # 更新tags（如果新的有tags）
                                    if tags_str:
                                        last_qa['tags'] = tags_str
                                else:
                                    # 如果节点不同，创建新QA对
                                    if current_robot_question:
                                        qa_pairs.append({
                                            current_node: {
                                                "robot": current_robot_question,
                                                "custom": user_answer
                                            },
                                            "tags": tags_str
                                        })

                # 再处理机器人新问题（如果存在）
                if record.get('answer_content'):
                    robot_text = ""
                    node_name = record.get('answer_text', '')
                    if "Q" not in node_name:
                        contents = record['contents']
                        for content in contents:
                            if "Q" in content['translate_text']:
                                node_name = content['translate_text'].split(":")[0]
                                break

                    # 从 contents 中提取文本
                    if record.get('contents'):
                        robot_text = ' '.join([c['translate_text'] for c in record['contents']])
                    else:
                        content = record['answer_content']
                        lines = content.split('\n')
                        robot_text = '\n'.join([line for line in lines if not line.strip().endswith('秒')])

                    # 清理文本
                    robot_text = robot_text.strip()
                    if ':' in robot_text:
                        parts = robot_text.split(':', 1)
                        if parts[0] in ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q6', 'Q7', 'Q1-A', 'Q1-default']:
                            robot_text = parts[1].strip()

                    current_robot_question = robot_text
                    current_node = node_name
                if idx == len(records) - 1:
                    # 处理最后一条记录，如果是用户回答但没有对应的机器人问题
                    if current_robot_question and current_node:
                        tags_list = []

                        tags_str = ','.join(tags_list) if tags_list else ''
                        qa_pairs.append({
                            current_node: {
                                "robot": current_robot_question,
                                "custom": ""
                            },
                            "tags": ""
                        })
        return qa_pairs

    def read_excel_data(self) -> pd.DataFrame:
        """读取Excel文件数据"""
        try:
            print(f"正在读取Excel文件: {self.excel_file}")
            df = pd.read_excel(self.excel_file)
            print(f"成功读取Excel文件，共 {len(df)} 行，{len(df.columns)} 列")
            print(f"列名: {list(df.columns)}")

            # 检查是否有"通话ID"列
            if self.record_id_column not in df.columns:
                raise ValueError(f"Excel文件中没有找到列: '{self.record_id_column}'")

            # 去除空白的通话ID
            df = df.dropna(subset=[self.record_id_column])
            df[self.record_id_column] = df[self.record_id_column].astype(str).str.strip()
            df = df[df[self.record_id_column] != ""]
            df['通话文本'] = df['通话文本'].str.replace('_x000D_', '', regex=False)

            print(f"处理后有效记录数: {len(df)}")
            return df
        except Exception as e:
            print(f"读取Excel文件失败: {str(e)}")
            raise

    def process_all_records(self) -> pd.DataFrame:
        """处理所有通话记录"""
        # 读取Excel数据
        df = self.read_excel_data()

        # 新增列
        df["接口返回结果"] = ""
        df["QA对提取结果"] = ""

        total_records = len(df)
        print(f"开始处理 {total_records} 条通话记录...")

        for i, (idx, row) in enumerate(df.iterrows(), start=1):
            record_id = row[self.record_id_column]
            print(f"处理进度: {i}/{total_records} - 通话ID: {record_id}")

            try:
                # 调用接口获取数据
                print(f"  正在调用接口获取通话 {record_id} 的详情...")
                api_result = self.fetch_agent_detail_json_sync(record_id)

                # 提取QA对
                print(f"  正在提取QA对...")
                qa_pairs = self.extract_qa_pairs(api_result)

                # 保存结果到DataFrame
                # 将JSON结果转换为字符串（限制长度以避免内存问题）
               # api_result_str = json.dumps(api_result, ensure_ascii=False, separators=(',', ':'))
                api_result_str = json.dumps(api_result, ensure_ascii=False, separators=(',', ':'))


                # 将QA对转换为字符串
               # qa_pairs_str = json.dumps(qa_pairs, ensure_ascii=False, separators=(',', ':'))
                qa_pairs_str = json.dumps(qa_pairs, ensure_ascii=False, indent=2)

                df.at[idx, "接口返回结果"] = api_result_str
                df.at[idx, "QA对提取结果"] = qa_pairs_str

                print(f"  成功处理通话 {record_id}")

                # 添加短暂延迟，避免请求过于频繁
                time.sleep(0.2)

            except Exception as e:
                error_msg = f"处理通话 {record_id} 时出错: {str(e)}"
                print(f"  {error_msg}")
                df.at[idx, "接口返回结果"] = f"错误: {str(e)}"
                df.at[idx, "QA对提取结果"] = f"错误: {str(e)}"

        print(f"所有通话记录处理完成!")
        return df

    def save_to_excel(self, df: pd.DataFrame, output_file: str = "1.csv"):
        """保存结果到CSV文件"""
        try:
            # 保存到CSV（使用utf-8-sig编码以支持中文）
            df.to_excel(output_file, index=False, encoding='utf-8-sig')
            print(f"结果已保存到: {output_file}")
            print(f"文件包含 {len(df)} 行，{len(df.columns)} 列")
        except Exception as e:
            print(f"保存CSV文件失败: {str(e)}")
            raise


def main():
    """主函数"""
    try:
        # 创建处理器实例
        fetcher = AgentDetailFetcher()

        # 处理所有记录
        result_df = fetcher.process_all_records()

        # 保存结果
        fetcher.save_to_excel(result_df, "asr_taizhou_jungongdan_trans_res.xlsx")

        # 打印统计信息
        total_records = len(result_df)
        print("\n" + "=" * 50)
        print("处理统计:")
        print(f"总记录数: {total_records}")
        print("=" * 50)

    except Exception as e:
        print(f"程序执行失败: {str(e)}")
        traceback.print_exc()


if __name__ == "__main__":
    # 设置pandas显示选项，避免打印时截断
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', None)
    pd.set_option('display.max_colwidth', None)

    main()