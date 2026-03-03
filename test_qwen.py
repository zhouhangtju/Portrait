import urllib.request
import urllib.error
import json
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def test_qwen_model():
    # 配置信息
    url = "http://188.103.147.179:30175/gateway/api/bMWPmH"

    headers = {
        "Content-Type": "application/json",
        "Authorization-Gateway": "sk-a2b25448-f74f-4c2f-a855-aed8e4251d01"
    }

    # 测试 Prompt
    test_prompt = "你好，请简单回复'测试成功'，不要输出其他多余内容。"

    payload = {
        "model": "Qwen2-72B-Instruct",
        "messages": [{"role": "user", "content": test_prompt}],
        "stream": False
    }

    logger.info(f"正在发送请求到: {url}")

    try:
        # 准备请求数据
        data = json.dumps(payload).encode('utf-8')

        # 创建请求对象
        req = urllib.request.Request(url, data=data, headers=headers, method='POST')

        # 发送请求 (设置超时为 30 秒)
        with urllib.request.urlopen(req, timeout=30) as response:
            if response.status != 200:
                logger.error(f"请求失败，状态码: {response.status}")
                return

            # 读取并解析响应
            response_body = response.read().decode('utf-8')
            data = json.loads(response_body)

            # 解析返回结构 (兼容 OpenAI 格式)
            if "choices" in data and len(data["choices"]) > 0:
                content = data["choices"][0]["message"]["content"]
                logger.info("✅ 模型调用成功！")
                logger.info(f"模型回复: {content}")
            else:
                logger.warning("⚠️ 返回数据格式异常，未找到 choices 字段")
                logger.info(f"完整返回数据: {data}")

    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else "无详细信息"
        logger.error(f"HTTP 错误: {e.code} - {e.reason}")
        logger.error(f"服务器返回: {error_body}")
    except urllib.error.URLError as e:
        logger.error(f"网络连接错误 (URL Error): {e.reason}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON 解析错误: {e}")
    except Exception as e:
        logger.error(f"发生未知错误: {e}")


if __name__ == "__main__":
    test_qwen_model()