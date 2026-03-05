# stat_hangup_nodes.py 说明

## 脚本作用
`stat_hangup_nodes.py` 用于从 PostgreSQL 表（默认 `call_record_enriched`）读取一段时间内的通话解析结果，并做两类节点统计（按 `task_id` 区分）：

1. 最后节点挂断统计（含拒识挂断数）
2. 倒数第二个节点挂断统计

其中“节点”来自 `qa_pairs` 中的节点标识。

## 统计口径

### 1) 最后节点统计 (`task_node_stats`)
- 对每条记录，解析 `qa_pairs`，取最后一个有效节点。
- 按 `(task_id, node)` 聚合：
  - `hangup_total`: 总挂断数
  - `hangup_robot`: `hangup_by == 1`
  - `hangup_user`: `hangup_by == 2`
  - `refuse_user_hangup`: 用户挂断且最后机器人话术包含拒识关键词（默认 `不好意思`）

### 2) 倒数第二个节点统计 (`task_node_stats_倒数第二个`)
- 对每条记录，解析 `qa_pairs`，取倒数第二个有效节点。
- 按 `(task_id, node)` 聚合：
  - `hangup_total`
  - `hangup_robot`
  - `hangup_user`

如果节点不足（如只有一个或没有），会记为 `UNKNOWN`。

## 输入参数
- `--start-date`: 开始日期（`YYYY-MM-DD`）
- `--end-date`: 结束日期（`YYYY-MM-DD`）
- `--task-id`: 可选，仅统计指定任务
- `--table-name`: 统计数据表名，默认 `call_record_enriched`
- `--refuse-keyword`: 拒识关键词，默认 `不好意思`
- `--output`: 输出 JSON 文件路径，默认 `hangup_stats.json`

## 输出内容
1. 终端打印：
- 总记录数、任务数、拒识关键词
- 每个 `task_id` 下两张统计表：
  - 最后节点统计
  - 倒数第二个节点统计

2. JSON 文件（`--output`）：
- `summary`
- `task_totals`
- `task_node_stats`
- `task_node_stats_倒数第二个`

## 主要函数说明

### `parse_args()`
解析命令行参数，提供默认值和帮助信息。

### `_parse_date(value)`
把日期字符串转为 `date` 对象。

### `_parse_qa_pairs(raw)`
兼容 `qa_pairs` 的多种格式（`None` / `str` / `list`）并统一返回 `list`。

### `_extract_last_node_and_robot_text(qa_pairs)`
从 `qa_pairs` 提取最后一个有效节点和该节点的 `robot` 话术文本。

### `_extract_prev_node(qa_pairs)`
提取倒数第二个有效节点；不足时返回 `UNKNOWN`。

### `_fetch_rows(table_name, start_date, end_date, task_id)`
从 PostgreSQL 查询目标时间段数据，读取字段：
- `callid`
- `task_id`
- `hangup_by`
- `qa_pairs`
- `phone`

### `_build_stats(rows, refuse_keyword)`
核心聚合逻辑，生成最终统计字典：
- 统计最后节点
- 统计倒数第二个节点
- 统计拒识用户挂断

### `_print_stats(stats)`
把统计结果按任务打印成可读表格。

### `main()`
主流程：
1. 读取参数
2. 初始化数据库连接
3. 查询数据并聚合
4. 打印结果
5. 输出 JSON 文件
6. 关闭数据库连接

## 运行示例
```bash
python scripts/stat_hangup_nodes.py \
  --start-date 2026-02-01 \
  --end-date 2026-02-28 \
  --task-id 29e374be-3313-49ed-8de4-c41d25589e0d \
  --refuse-keyword "不好意思" \
  --output hangup_stats.json
```
