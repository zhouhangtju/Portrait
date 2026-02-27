"""
LLM 服务 - 情感分析与风险识别

支持双环境：
- 开发环境: 通义千问 API (DashScope)
- 生产环境: 自定义网关 API
"""

import asyncio
import json
from datetime import datetime
from typing import Any

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.config import settings


# 情感分析 Prompt
SENTIMENT_PROMPT = """分析以下外呼通话内容，评估客户的情绪和风险。

通话内容:
{dialogue}

请严格按照以下 JSON 格式返回分析结果，不要返回其他内容:
{{
    "sentiment": "positive/neutral/negative",
    "sentiment_score": 0.0-1.0,
    "complaint_risk": "low/medium/high",
    "churn_risk": "low/medium/high",
    "reason": "简要分析原因(50字以内)"
}}

分析要点:
- sentiment: 客户整体情绪倾向
- sentiment_score: 情绪得分，0=极度负面，1=极度正面
- complaint_risk: 投诉风险，检测"投诉"、"举报"、"工信部"等关键词
- churn_risk: 流失风险，检测"不用了"、"取消"、"换运营商"等关键词
"""

EMOTION_PROMPT = """你是质检判定模型。请根据“通话文本”判断用户情绪。

判定标准（务必遵守）：
1. negative：仅在用户出现明显抱怨、指责、辱骂、威胁投诉/曝光、强烈不耐烦/抵触（如“别打了”“不想说了”）/低分（≤6分）等成立。
2. positive：用户出现明确认可/感谢/夸赞/配合/明确给出高分（≥9分/10分）时成立，并且整体语气积极。
3. neutral：仅陈述事实或流程性回应（如“嗯”“好”“知道了”），或情绪不明显/混合但不强烈。
4. 若文本既有轻微正面也有轻微负面，以更强烈的一方为准；若强度相近则输出 neutral。
5. 不要被“话术诱导打10分”误导，必须以用户真实表达为准。

输出必须是严格 JSON（不要多余文字）：
{{
  "label": "neutral|positive|negative",
  "confidence": 0.0-1.0
}}

通话文本如下：
{dialogue_text}
"""

SATISFACTION_PROMPT = '''你是质检判定模型。请根据“通话文本”判断用户对本次服务是否满意。

判定标准（务必遵守）：
1. satisfied：仅在用户明确表达满意/认可/感谢/夸赞，或明确给出高分（≥9分/10分）时成立。
2. unsatisfied：在用户明确抱怨/否定/指责/要求投诉/要求返工/低分（≤6分）等成立。
3. neutral：若用户未表达态度、或态度模糊、或仅回答流程性问题（如“嗯”“好”“知道了”），输出“无法判断”。
4. 不要被“话术诱导打10分”误导，必须以用户真实表达为准。

输出必须是严格 JSON（不要多余文字）：
{{
  "label": "satisfied|unsatisfied|neutral",
  "confidence": 0.0-1.0,
}}

通话文本如下：
{dialogue_text}
'''

COMPLAINT_PROMPT = '''你是质检判定模型。请根据“通话文本”判断用户是否存在投诉风险。

判定标准（务必遵守）：
1. high：仅在用户明确表达要投诉/已投诉/继续反映、威胁向上级或监管部门投诉、明确要求返工、更换人员/方案，或伴随强烈指责、辱骂、激烈情绪且问题未解决时成立。
2. medium：在用户明确表达不满、抱怨、质疑服务质量或处理结果，但未直接提出投诉或升级要求或用户态度偏负面，对处理结果仅勉强接受、表示保留意见时成立。
3. low：在用户未表达明显不满或升级意图，或已接受处理结果、表示理解/认可/感谢，或通话内容仅为流程性沟通时成立。
4. 若用户未明确表达态度，或信息不足以判断投诉风险，输出“medium”，不要猜测。
5. 不要被“话术诱导打10分”误导，必须以用户真实表达为准。

输出必须是严格 JSON（不要多余文字）：
{{
  "label": "high|medium|low",
  "confidence": 0.0-1.0
}}

通话文本如下：
{dialogue_text}
'''

CHURN_PROMPT = '''你是质检判定模型。请根据“通话文本”判断用户是否存在流失风险。

判定标准（务必遵守）：
1. high：仅在用户明确表达要停用/退订/携号转网/换运营商，或明确表示将不再使用本业务/本服务,或用户明确表达强烈不满且拒绝继续使用、拒绝继续处理，存在明确离网倾向时成立。
2. medium：在用户表达不满、抱怨费用/质量/服务，或提出“考虑换”“再看看”“不行就换”等倾向性表述，存在潜在流失风险但未明确提出退订/转网/停用时成立。
3. low：在用户未表达离网/退订/转网意图，或明确表示继续使用/先用着/已接受处理结果，或通话内容仅为流程性沟通时成立。
4. 若用户未明确表达是否会停用/退订/转网，或信息不足以判断流失风险，输出“medium”，不要猜测。
5. 不要被“话术诱导打10分”误导，必须以用户真实表达为准。

输出必须是严格 JSON（不要多余文字）：
{{
  "label": "high|medium|low",
  "confidence": 0.0-1.0
}}

通话文本如下：
{dialogue_text}
'''
# 问卷场景
UNSATISFIED_REASON_PROMPT = '''
你是一个客服回访质检引擎，只能在给定候选集合中选择“不满意原因”。

【候选原因】{candidates}

【对话片段】（仅包含与不满意原因相关的关键问答）
{seg_text}

【输出要求】
- 只能输出一个 JSON，对应字段必须是 reason
- reason 必须严格等于候选原因中的某一个字符串
- 如果对话片段无法判断或用户未表达不满意原因，请输出 {{"reason": "接通未评价"}}

现在请输出 JSON：
'''

VISIT_PROMPT = '''
你是客服通话质检中的“上门需求判定器”。请基于给定对话文本判断：是否需要安排工作人员上门处理。

判定规则（尽量保守，减少误派单）：
- 输出 "yes"：用户明确要求上门/必须来现场/让师傅来看看；或用户明确描述“已约上门但未到/师傅没准时来/一直不来/爽约”等履约问题；或用户描述的网络/设备问题明显需要现场排查（如反复断网、装机后无法使用、光猫/线路疑似故障且远程无法处理）。
- 输出 "no"：仅咨询、解释、信息确认、已解决、用户拒绝上门、仅要求电话处理；或文本信息不足以确定需要上门。
- 若判断不确定或证据不足：输出 "no"。

重要约束：
1) 仅输出合法 JSON，不得输出多余文本。
2) 字段固定为 visit_needed，值只能是 "yes" 或 "no"。
3) 不得编造对话中不存在的事实。

对话文本：
{dialogue_text}

请输出：
{{"visit_needed":"yes"}} 或 {{"visit_needed":"no"}}
'''
# 如果没没有就模型输出
VISIT_REASON_PROMPT = '''
你是客服通话质检中的“上门原因分类器”。已确认需要上门，请根据对话文本在下列候选原因中选择一个最贴近的原因。

候选原因（只能从中选择一个）：
1) 前台服务问题：客服人员业务不熟练或办理业务慢/客服人员业务解释不清晰、不完整/客服人员语气生硬、不耐烦、不回答问题等服务相关。
2) 装维服务问题：装维人员安装、调试、维修质量差/装维人员服务态度差/装维人员违规收费/装维人员安装、联系、维修不及时等装维相关。
3) 家庭宽带问题：LOS红灯/无法上网/光猫掉电/光猫损坏/机顶盒损坏、无法开机/路由器死机、损坏、设置错误/视频播放不流畅、无法播放/网页打不开、内容无法正常访问、速度慢/游戏运行不流畅/直播卡顿/网络故障/网速慢/频繁掉线/网络无法连接/无WIFI信号或WIFI信号弱等网络质量相关。
4) 其他原因：非移动宽带用户/使用良好，评价错误/人力不足造成装维不及时等客观原因

判定规则：
- 优先匹配“最直接、最主要”的诉求与证据；如果多类同时出现，按对用户影响最大的主因选择。
- 若无法确定主因：选择“其他原因”。

重要约束：
1) 仅输出合法 JSON，不得输出多余文本。
2) 字段固定为 visit_reason。
3) visit_reason 的值只能是以下四个之一：
   "前台服务问题" / "装维服务问题" / "家庭宽带问题" / "其他原因"
4) 不得编造对话中不存在的事实。

对话文本：
{dialogue_text}

请输出示例：
{{"visit_reason":"家庭宽带问题"}}
'''


class LLMService:
    """
    LLM 服务类

    统一封装 LLM API 调用，支持开发/生产双环境
    """

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=settings.llm_timeout)
        self._semaphore = asyncio.Semaphore(settings.llm_max_concurrent)

    async def close(self):
        """关闭 HTTP 客户端"""
        await self.client.aclose()

    @property
    def is_gateway_mode(self) -> bool:
        """是否使用网关模式"""
        return settings.llm_gateway_mode

    async def analyze_sentiment(self, dialogue: str) -> dict[str, Any]:
        """
        分析对话情感和风险

        Args:
            dialogue: 对话文本

        Returns:
            分析结果字典
        """
        if not dialogue or not dialogue.strip():
            return self._default_result("empty_dialogue")

        prompt = SENTIMENT_PROMPT.format(dialogue=dialogue)

        try:
            response = await self._call_llm(prompt)
            result = self._parse_response(response)
            return result
        except Exception as e:
            logger.error(f"LLM 分析失败: {e}")
            return self._default_result(f"error: {str(e)}")

    async def portrait_analysis_llm(self, dialogue: str, candidates: list = None, portrait_label: str = None):
        """
        用户画像分析

        Args:
            dialogue: 对话文本

        Returns:
            分析结果字典
        """
        if not dialogue or not dialogue.strip():
            return self._default_result("empty_dialogue")

        prompt = None

        if portrait_label == 'satisfaction':
            prompt = SATISFACTION_PROMPT.format(dialogue_text=dialogue)
        elif portrait_label == 'emotion':
            prompt = EMOTION_PROMPT.format(dialogue_text=dialogue)
        elif portrait_label == 'complaint':
            prompt = COMPLAINT_PROMPT.format(dialogue_text=dialogue)
        elif portrait_label == 'churn':
            prompt = CHURN_PROMPT.format(dialogue_text=dialogue)
        elif portrait_label == 'unsatisfied_reason':
            prompt = UNSATISFIED_REASON_PROMPT.format(seg_text=dialogue,candidates=candidates)
        elif portrait_label == 'visit_needed':
            prompt = VISIT_PROMPT.format(dialogue_text=dialogue)
        elif portrait_label == 'visit_reason':
            prompt = VISIT_REASON_PROMPT.format(dialogue_text=dialogue)

        try:
            response = await self._call_llm(prompt)
            response = response.strip()

            # 处理 markdown 代码块
            if response.startswith("```"):
                lines = response.split("\n")
                response = "\n".join(lines[1:-1])

            result = json.loads(response)
            return result
        except Exception as e:
            logger.error(f"LLM 分析失败: {e}")
            return self._default_result(f"error: {str(e)}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _call_llm(self, prompt: str) -> str:
        """
        调用 LLM API

        根据配置自动选择开发环境 API 或生产网关

        Args:
            prompt: 提示词

        Returns:
            LLM 响应文本
        """
        async with self._semaphore:
            if self.is_gateway_mode:
                return await self._call_gateway_api(prompt)
            else:
                return await self._call_qwen_api(prompt)

    async def _call_qwen_api(self, prompt: str) -> str:
        """
        调用通义千问 API (开发环境)

        使用 OpenAI 兼容格式
        """


        # 请求头（包含认证）

        # url = f"{settings.llm_api_base_url}"

        # headers = {
        #     "Content-Type": "application/json",
        #     "Authorization": f"Bearer {settings.llm_api_key}",
        # }

        url = "http://188.103.147.179:30175/gateway/api/bMWPmH"
        headers = {
            "Content-Type": "application/json",
            "Authorization-Gateway": "sk-a2b25448-f74f-4c2f-a855-aed8e4251d01"
        }

        payload = {
            "model": "Qwen2-72B-Instruct",
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            # "temperature": 0.3,
            # "max_tokens": 500,
        }

        logger.debug(f"调用通义千问 API: {settings.llm_model}")

        response = await self.client.post(url, headers=headers, json=payload)
        response.raise_for_status()

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return content

    async def _call_gateway_api(self, prompt: str) -> str:
        """
        调用网关 API (生产环境)

        使用自定义网关认证
        """
        url = settings.llm_api_base_url

        headers = {
            "Content-Type": "application/json",
            "Authorization-Gateway": settings.llm_gateway_auth_header,
        }

        payload = {
            "model": settings.llm_model,
            "stream": False,
            "messages": [{"role": "user", "content": prompt}],
        }

        logger.debug(f"调用网关 API: {settings.llm_model}")

        response = await self.client.post(url, headers=headers, json=payload)
        response.raise_for_status()

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return content

    def _parse_response(self, response: str) -> dict[str, Any]:
        """
        解析 LLM 响应

        Args:
            response: LLM 原始响应

        Returns:
            解析后的结果字典
        """
        try:
            # 尝试提取 JSON
            response = response.strip()

            # 处理 markdown 代码块
            if response.startswith("```"):
                lines = response.split("\n")
                response = "\n".join(lines[1:-1])

            result = json.loads(response)

            # 验证必需字段
            required = ["sentiment", "sentiment_score", "complaint_risk", "churn_risk"]
            for field in required:
                if field not in result:
                    result[field] = self._default_value(field)

            # 规范化值
            result["sentiment"] = self._normalize_sentiment(result["sentiment"])
            result["sentiment_score"] = max(0.0, min(1.0, float(result["sentiment_score"])))
            result["complaint_risk"] = self._normalize_risk(result["complaint_risk"])
            result["churn_risk"] = self._normalize_risk(result["churn_risk"])
            result["raw_response"] = response

            return result

        except json.JSONDecodeError as e:
            logger.warning(f"解析 LLM 响应失败: {e}, response={response[:200]}")
            return self._default_result(f"parse_error: {response[:100]}")

    def _normalize_sentiment(self, value: str) -> str:
        """规范化情感值"""
        value = str(value).lower().strip()
        if value in ["positive", "积极", "正面"]:
            return "positive"
        elif value in ["negative", "消极", "负面"]:
            return "negative"
        else:
            return "neutral"

    def _normalize_risk(self, value: str) -> str:
        """规范化风险值"""
        value = str(value).lower().strip()
        if value in ["high", "高"]:
            return "high"
        elif value in ["medium", "中"]:
            return "medium"
        else:
            return "low"

    def _default_value(self, field: str) -> Any:
        """返回字段默认值"""
        defaults = {
            "sentiment": "neutral",
            "sentiment_score": 0.5,
            "complaint_risk": "low",
            "churn_risk": "low",
        }
        return defaults.get(field)

    def _default_result(self, reason: str) -> dict[str, Any]:
        """返回默认结果"""
        return {
            "sentiment": "neutral",
            "sentiment_score": 0.5,
            "complaint_risk": "low",
            "churn_risk": "low",
            "reason": reason,
            "raw_response": None,
        }

    async def analyze_pending_batch(self, limit: int = 100) -> dict[str, Any]:
        """
        批量分析待处理的通话记录

        Args:
            limit: 最大处理数量

        Returns:
            处理结果统计
        """
        from src.services.etl_service import etl_service
        from src.core.database import get_portrait_db
        from sqlalchemy import text

        logger.info(f"开始批量 LLM 分析 (limit={limit})")

        # 获取待分析记录
        records = await etl_service.get_pending_records_for_analysis(limit)

        if not records:
            logger.info("没有待分析的记录")
            return {"status": "success", "analyzed": 0, "skipped": 0}

        logger.info(f"待分析记录数: {len(records)}")

        analyzed = 0
        skipped = 0
        errors = 0

        for record in records:
            try:
                # 获取 ASR 对话文本
                dialogue = await etl_service.get_asr_text_for_analysis(
                    record.callid,
                    record.call_date,
                )

                if not dialogue:
                    skipped += 1
                    continue

                # 调用 LLM 分析
                result = await self.analyze_sentiment(dialogue)

                # 更新记录
                async for session in get_portrait_db():
                    await session.execute(
                        text("""
                            UPDATE call_record_enriched
                            SET sentiment = :sentiment,
                                sentiment_score = :sentiment_score,
                                complaint_risk = :complaint_risk,
                                churn_risk = :churn_risk,
                                llm_analyzed_at = :analyzed_at,
                                llm_raw_response = :raw_response,
                                updated_at = :updated_at
                            WHERE id = :id
                        """),
                        {
                            "id": record.id,
                            "sentiment": result["sentiment"],
                            "sentiment_score": result["sentiment_score"],
                            "complaint_risk": result["complaint_risk"],
                            "churn_risk": result["churn_risk"],
                            "analyzed_at": datetime.now(),
                            "raw_response": result.get("raw_response", "")[:2000],
                            "updated_at": datetime.now(),
                        },
                    )
                    await session.commit()

                analyzed += 1

                # 批量处理间隔，避免 API 限流
                if analyzed % 10 == 0:
                    logger.info(f"已分析 {analyzed}/{len(records)} 条")
                    await asyncio.sleep(0.5)

            except Exception as e:
                logger.error(f"分析记录 {record.callid} 失败: {e}")
                errors += 1

        logger.info(f"LLM 分析完成: analyzed={analyzed}, skipped={skipped}, errors={errors}")

        return {
            "status": "success",
            "analyzed": analyzed,
            "skipped": skipped,
            "errors": errors,
        }


# 全局服务实例
llm_service = LLMService()
