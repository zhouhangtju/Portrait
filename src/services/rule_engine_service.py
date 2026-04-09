"""
规则引擎服务 - 基于规则的满意度/情绪/风险分析

不使用大模型，纯基于关键词和规则进行分析
"""
import json
import re
from dataclasses import dataclass
from typing import Optional, Literal, List
from loguru import logger


# ===========================================
# 关键词库配置
# ===========================================

# 投诉风险关键词
from .llm_service import LLMService
from .voice_analyze_emotion import VoiceEmotionService
# from src.services import llm_service

COMPLAINT_KEYWORDS = {
    'high': [
        # 投诉相关
        '投诉', '举报', '工信部', '消费者协会', '12315', '曝光', '315',
        # 欺骗相关
        '骗人', '骗子', '欺诈', '诈骗', '坑人', '骗钱', '黑心',
        # 强烈负面
        '垃圾', '太差', '差劲', '恶心', '烂', '废物', '坑爹', '狗屎',
        # 升级投诉
        '找领导', '找经理', '上级', '总部', '你们领导', '负责人',
        # 法律相关
        '起诉', '律师', '法律', '赔偿', '法院', '告你们',
        # 媒体相关
        '曝光', '记者', '新闻', '媒体',
    ],
    'medium': [
        # 不满意表达
        '不满意', '很差', '太差', '问题', '故障', '没解决', '解决不了',
        # 收费问题
        '太慢', '太贵', '乱收费', '多扣', '扣费', '多收', '收费不合理',
        # 服务态度
        '态度差', '服务差', '不专业', '敷衍', '推诿', '踢皮球',
        # 重复问题
        '催了好几次', '一直没', '拖', '多少次了', '等了很久', '说话不算',
        # 失望表达
        '失望', '无语', '受不了', '忍不了',
    ],
}

# 流失风险关键词
CHURN_KEYWORDS = {
    'high': [
        # 明确取消意向
        '不用了', '取消', '退订', '销户', '注销', '不要了', '退了吧',
        # 转网意向
        '换运营商', '换电信', '换联通', '换移动', '携号转网', '转网',
        # 套餐变更
        '换套餐', '降档', '降套餐', '最低套餐', '取消套餐',
        # 停机销户
        '不续费', '停机', '停用', '不交费', '欠费停机',
    ],
    'medium': [
        # 考虑中
        '考虑', '再说', '看看', '比较一下', '对比', '犹豫',
        # 价格敏感
        '太贵', '划不来', '不值', '性价比', '便宜点',
        # 使用减少
        '很少用', '用不上', '没必要', '不常用', '用得少',
        # 竞品对比
        '别家', '其他', '朋友用的', '隔壁', '竞争对手',
        # 减少消费
        '少打点', '少用', '降费',
    ],
}

# 满意度 - ASR 标签映射
SATISFACTION_ASR_TAGS = {
    'satisfied': ['满分', 'Q7-满分', 'Q9-满分', 'Q5-满分', 'Q6-满分', 'Q10-满分', 
                  '非常满意', '很满意', '十分满意'],
    'unsatisfied': ['非满分', 'Q7-非满分', 'Q9-非满分', 'Q5-非满分', '不满意', 
                    '非常不满意', '很不满意'],
    'neutral': ['一般', 'Q8', 'default', '还可以'],
}

# 满意度 - 用户打分识别 (正则表达式)
SCORE_PATTERNS = {
    'satisfied': [
        r'10分', r'十分', r'9分', r'九分', r'满分',
    ],
    'neutral': [
        r'8分', r'八分', r'7分', r'七分', r'6分', r'六分',
    ],
    'unsatisfied': [
        r'[0-5]分', r'零分', r'一分', r'两分', r'三分', r'四分', r'五分',
    ],
}

# 满意度 - 关键词兜底
SATISFACTION_KEYWORDS = {
    'satisfied': [
        '满意', '很好', '不错', '可以', '好的', '挺好', '没问题', '谢谢',
        '感谢', '辛苦了', '解决了', '处理好了', '修好了', '正常了',
        '专业', '态度好', '服务好', '效率高',
    ],
    'unsatisfied': [
        '不满意', '不好', '差', '不行', '有问题', '没解决', '还是不行',
        '太慢', '太差', '失望', '没用', '白打',
    ],
    'neutral': [
        '一般', '还行', '凑合', '马马虎虎', '还好', '普通', '就那样',
    ],
}

# 情绪关键词
EMOTION_KEYWORDS = {
    'positive': [
        # 积极词汇
        '好', '谢谢', '感谢', '满意', '不错', '可以', '行', '嗯', '好的',
        '解决了', '修好了', '正常了', '快', '方便', '专业', '耐心',
        '辛苦', '帮忙', '感激', '棒', '赞', '厉害', '优秀',
        # 配合态度
        '好的好的', '没问题', '知道了谢谢', '明白', '清楚',
    ],
    'negative': [
        # 负面词汇
        '不好', '差', '烦', '急', '气', '怒', '投诉', '问题', '故障',
        '没用', '骗', '坑', '垃圾', '恶心', '讨厌', '烂', '废',
        '慢', '贵', '差劲', '失望', '无语', '搞什么', '什么玩意',
        # 负面情绪
        '烦死了', '受不了', '忍不了', '太过分', '算了吧', '不想说了',
        '别打了', '不要打了', '挂了', '不听', '不接受',
    ],
    'neutral': [
        '哦', '嗯', '知道了', '好吧', '行吧', '再说', '看看',
        '那行', '可以', '好', '是的',
    ],
}

# 防骚扰关键词 (用户反感回访/骚扰意向)
HARASSMENT_KEYWORDS = {
    'high': [
        # 明确拒绝/反感
        '别打电话', '别再打', '不要打', '以后别打', '别再联系', '不要再问',
        '烦不烦', '烦死了', '烦不烦啊', '太烦了', '真烦', '啰嗦',
        '问了好几遍', '问了好几次', '还问', '重复问', '问了又问',
        '骚扰', '别骚扰', '骚扰我', '恶意骚扰',
        '投诉', '再问投诉', '再打投诉', '举报', '拉黑', '屏蔽',
        '没完没了', '有完没完', '够了', '适可而止',
    ],
}

# 装机单竣工回访
INSTALL_FINISH_TASKS = {
        "593ef3d3-2fd2-4241-a171-3b3984f35f67",
        "2ff1d49c-44f1-479a-914d-08b98c151ab5",
        "5673d783-13c9-4cc5-bcef-3abc22286c41",
        "eca85f1e-3558-40ec-8140-79f75f36eb57",
        "178fe85f-282e-4945-b9ec-64d2abf361ab",
        "08374546-f421-4d88-a3f7-2bf74811a005",
        "68f6c619-d084-48f9-ad8d-b67fef1b6f2a",
        "e7c484aa-db16-486d-ac8c-534658e65139",
        "a1cecf8b-1e15-4f3e-9201-c2398128a2ee",
        "a8e7c2b2-23ac-4986-8346-67735605dd5c",
        "62086274-9e11-40d5-9cf0-a40d944f5d60",
        "9ea09f9f-3b64-4037-a3fa-e83af34ecf12",
        "83eecedd-90c5-4a2a-b4cf-ea2d68e4842f",
        "1dcce3a0-48a0-4174-bb99-c464e8f796d3",
    }
# 投诉单报结回访
COMPLAINT_CLOSE_TASKS = {
        "aa794389-ae0e-4ac0-be31-90d715465b54",
        "3fd099de-a62f-4d54-b713-0d417d313faa",
        "c7058289-7782-419d-b7b0-7359e3da1ccf",
        "29e374be-3313-49ed-8de4-c41d25589e0d",
        "746e42f0-15c8-4ce0-b529-a0174d087160",
        "5b81315f-9cac-42b6-8118-f8210655541e",
        "bf73a3fb-f412-40fc-b819-d05b6fb6e813",
        "3a418073-f156-49e3-afe1-d77a248f0388",
        "6114b08a-c48e-4f53-a9bd-7ad1e69ef871",
        "6277e6dc-49c8-4264-8b1f-585941ba7e46",
        "ba885176-28ce-47b9-8e00-8315e6affcd6",
        "c0b53cc2-fdc1-4b64-bb54-4aaaf653f649",
        "ba508c01-c348-47eb-87f4-8e5e1fe98265",
        "12ab2adb-cb8c-4fe9-b10f-bbce2ae4dff6",
    }
# 质差修复已上门
QOE_VISIT_TASKS = {
        "95e6eab9-32a1-41e8-96be-27beef62887d",
        "0764b0db-4d9a-42a4-a772-f6e0168fc775",
        "43fad8cd-ed0c-44e8-a739-5721725de6da",
        "b01baa38-6e8b-41fc-a6c9-c8de27f580fb",
        "65b22203-70d3-4719-8d8d-f4b876c8b6ed",
        "7f021fd0-8691-4344-8523-47e2a1c55d39",
        "29c274df-0702-4aca-9089-174b3fce5f67",
        "8be742e5-201d-469a-8e60-362db44cdced",
        "e6799d55-9224-4040-91a1-97edbf8ce022",
        "142c223a-6e91-4328-8aad-35ac01369c55",
        "8cc4a510-58fa-45a6-939d-576d6e5efc3f",
        "812aaa9e-ac7d-45d3-8b85-e386a9c48f16",
        "1634ee8d-a387-47f8-8ba6-4cb62e59e701",
        "221dc6df-6c23-44a4-ab6b-cb2d9e2eae01",
    }
# 质差派单问卷
QOE_SURVEY_TASKS = {
        "f54fe136-4469-42a7-a49e-5a5c3de66286",
        "1a398f6e-f63c-4471-91d5-a0c96ca35937",
        "71fb4197-0244-4289-9229-6f3ebf65f0be",
        "62c9e697-0350-45ed-a76b-447699ed1c47",
        "2e0abd56-218a-492e-9b68-3205bbfee9e5",
        "033f39f8-c4d6-4518-a342-f1fc174196d4",
        "3bc99a51-78d1-4b9B-bc7c-b72e70361991",
	"79b3c253-7408-4dbc-9b70-8fd7888bc216",
        "9317f3b8-fd9f-4f26-a0f7-a449ab01a23a",
        "aaed1735-e562-4cdc-b9c0-494e53e91525",
        "cd943a3d-a375-402c-b82f-3e13370a72ba",
        "88b5fa9e-ecbd-491f-baad-25731a75e894",
        "c0a86462-1e30-407f-a662-25e79f764b04",
        "928ea078-337e-4d43-a535-7516ff5bd5bc",
    }


@dataclass
class AnalysisResult:
    """单通电话分析结果"""
    
    satisfaction: Optional[str] = None  # satisfied/neutral/unsatisfied
    satisfaction_source: Optional[str] = None  # asr_tag/score/keyword
    satisfaction_llm_res: Optional[str] = None
    emotion: Optional[str] = None  # positive/neutral/negative
    emotion_llm_res: Optional[str] = None
    emotion_asr_res: Optional[str] = None
    complaint_risk: str = 'low'  # high/medium/low
    complaint_llm_res: Optional[str] = None
    churn_risk: str = 'low'  # high/medium/low
    churn_llm_res: Optional[str] = None
    willingness: Optional[str] = None  # 深度/一般/较低
    risk_level: Optional[str] = None  # 综合风险: churn/complaint/medium/none
    unsatisfied_reason: Optional[str] = None
    visit_needed: str = None
    visit_reason: str = None
    harassment_risk: str = 'no'  # yes/no (是否防骚扰)
    harassment_llm_res: Optional[str] = None



async def get_risk_level(complaint_risk: str, churn_risk: str) -> str:
    """
    根据投诉风险和流失风险计算综合风险等级
    
    优先级：流失风险高 > 投诉风险高 > 一般 > 无风险
    
    Args:
        complaint_risk: 投诉风险 high/medium/low
        churn_risk: 流失风险 high/medium/low
        
    Returns:
        综合风险等级: churn(流失风险)/complaint(投诉风险)/medium(一般)/none(无风险)
    """
    # 高风险优先
    if churn_risk == 'high':
        return 'churn'
    if complaint_risk == 'high':
        return 'complaint'
    
    # 任一有 medium 风险
    if complaint_risk == 'medium' or churn_risk == 'medium':
        return 'medium'
    
    # 都是 low，无风险
    return 'none'


class RuleEngineService:


    """
    规则引擎服务
    
    基于关键词和规则进行满意度/情绪/风险分析
    """
    llm_service = LLMService()
    voice_analyze_emotion = VoiceEmotionService()

    async def analyze_call(
        self,
        qa_pairs: list[dict],
        task_id: str,
        voice_url: List,
        duration: int = 0,
        rounds: int = 0,
    ) -> AnalysisResult:
        """
        分析单通电话
        
        Args:
            user_text: 用户说话内容（ASR 识别文本拼接）
            asr_labels: ASR 标签列表（如 Q7-满分）
            duration: 通话时长（秒）
            rounds: 交互轮次
            
        Returns:
            分析结果
        """
        result = AnalysisResult()

        
        # 1. 满意度分析（ASR标签 > 用户打分 > 关键词）
        satisfaction, source, satisfaction_llm_res =await self._analyze_satisfaction(qa_pairs)
        result.satisfaction = satisfaction
        result.satisfaction_source = source
        result.satisfaction_llm_res = satisfaction_llm_res
        
        # 2. 情绪分析（纯规则引擎）
        emotion, emotion_llm_res, emotion_asr_res = await self._analyze_emotion(qa_pairs, voice_url)
        result.emotion = emotion
        result.emotion_llm_res = emotion_llm_res
        result.emotion_asr_res = emotion_asr_res
        
        # 3. 投诉风险分析
        complaint_risk, complaint_llm_res = await self._analyze_complaint_risk(qa_pairs,task_id)
        result.complaint_risk = complaint_risk
        result.complaint_llm_res = complaint_llm_res
        
        # 4. 流失风险分析
        churn_risk, churn_llm_res = await self._analyze_churn_risk(qa_pairs)
        result.churn_risk = churn_risk
        result.churn_llm_res = churn_llm_res

        # 5. 沟通意愿判断
        result.willingness = await self._analyze_willingness(duration, rounds)
        
        # 6. 综合风险等级
        result.risk_level = await get_risk_level(result.complaint_risk, result.churn_risk)

        #7. 不满意原因
        result.unsatisfied_reason = await self.get_unsatisfied_reason(qa_pairs,task_id)

        #8. 用户是否需要上门及上门原因
        visit_needed, visit_reason = await self.get_visit_and_reasoin(qa_pairs)
        result.visit_needed = visit_needed
        result.visit_reason = visit_reason

        # 8. 是否防骚扰分析
        harassment_risk, harassment_llm_res = await self._analyze_harassment_risk(qa_pairs)
        result.harassment_risk = harassment_risk
        result.harassment_llm_res = harassment_llm_res
        
        return result



    async def qa_pairs_to_user_text_and_labels(
            self,
            qa_pairs: list[dict],
    ) -> tuple[str, list[str]]:

        user_text: list[str] = []
        asr_labels: list[str] = []
        META_KEYS = {"tags", "notify"}

        # 1) 解析 qa_pairs
        for item in qa_pairs:
            # tags → labels
            tags_str = (item.get("tags") or "").strip()
            if tags_str:
                for t in tags_str.split(","):
                    t = t.strip()
                    if t:
                        asr_labels.append(t)

            # custom → user_text
            for k, v in item.items():
                if k in META_KEYS:
                    continue
                custom = (v or {}).get("custom", "")
                custom = (custom or "").strip()
                if custom:
                    user_text.append(custom)

        return " ".join(user_text), asr_labels

    async def _extract_question_qa_text(self, qa_pairs: list[dict], keys: list[str]) -> list[dict]:
        """
        从 qa_pairs 中抽取指定 question key（如 Q4、Q4-default）的 robot/custom 文本片段。
        返回结构化片段列表，便于拼 prompt。
        """
        segs: list[dict] = []
        for item in qa_pairs:
            for k in keys:
                if k in item and isinstance(item.get(k), dict):
                    robot = (item[k].get("robot") or "").strip()
                    custom = (item[k].get("custom") or "").strip()
                    # 过滤空片段
                    segs.append({
                        k: {
                            "robot": robot,
                            "custom": custom,
                        }
                    })
        return segs
    
    async def _analyze_satisfaction(self,qa_pairs: list[dict], weights: Optional[dict] = None):
        ##### 1. 检查满意度标签 #####
        user_text, asr_labels = await self.qa_pairs_to_user_text_and_labels(qa_pairs)
        logger.info(f"user_text: {user_text};asr_labels: {asr_labels}")
        if any("不满意" in label for label in asr_labels):
            tag_label = "unsatisfied"
            tag_conf = 0.80
        elif any("满意" in label for label in asr_labels):
            tag_label = "satisfied"
            tag_conf = 0.80
        else:
            tag_label = "neutral"
            tag_conf = 0.30

        ##### 2. 检查用户原话打分 #####
        if "1分" in asr_labels or "2分" in asr_labels or "3分" in asr_labels or "4分" in asr_labels or "5分" in asr_labels:
            score_label = "unsatisfied"
            score_conf = 0.70
        elif "6分" in asr_labels or "7分" in asr_labels:
            score_label = "neutral"
            score_conf = 0.60
        elif "8分" in asr_labels or "9分" in asr_labels or "10分" in asr_labels:
            score_label = "satisfied"
            score_conf = 0.70
        else:
            score_label = "neutral"
            score_conf = 0.30

        ##### 3. llm预测
        cleaned = []
        for record in qa_pairs:
            r = dict(record)
            r.pop("tags", None)
            cleaned.append(r)

        result_str = json.dumps(
            cleaned,
            ensure_ascii=False,
        )


        result = await self.llm_service.portrait_analysis_llm(result_str, portrait_label="satisfaction")
        logger.info(f"llm_result: {result}")
        llm_label = result.get("label")
        llm_conf = result.get("confidence", 0.0)

        ##### 综合判断 #####
        weights = weights or {"tag": 0.30, "score": 0.45, "llm": 0.25}
        # 计算加权得分
        scores = {"satisfied": 0.0, "unsatisfied": 0.0}
        used = []

        if tag_label in ("satisfied", "unsatisfied") and tag_conf > 0 and weights["tag"] > 0:
            scores[tag_label] += weights["tag"] * tag_conf
            used.append({"label": tag_label, "confidence": tag_conf, "weight": weights["tag"]})

        if score_label in ("satisfied", "unsatisfied") and score_conf > 0 and weights["score"] > 0:
            scores[score_label] += weights["score"] * score_conf
            used.append({"label": score_label, "confidence": score_conf, "weight": weights["score"]})

        if llm_label in ("satisfied", "unsatisfied") and llm_conf > 0 and weights["llm"] > 0:
            scores[llm_label] += weights["llm"] * llm_conf
            used.append({"label": llm_label, "confidence": llm_conf, "weight": weights["llm"]})

        # tie-break：若都为0，则无法判断
        if scores["satisfied"] == 0 and scores["unsatisfied"] == 0:
            return "neutral","asr_tag+score+llm", llm_label

        final_label = "satisfied" if scores["satisfied"] >= scores["unsatisfied"] else "unsatisfied"
        final_score = scores[final_label]

        # 你也可以加一个“差值门槛”，差值太小就输出无法判断
        gap = abs(scores["satisfied"] - scores["unsatisfied"])
        if gap < 0.1:  # 可调
            return "neutral","asr_tag+score+llm", llm_label

        return final_label, "asr_tag+score+llm", llm_label

    async def _analyze_emotion(self,qa_pairs: list[dict], voice_url: list, weights: Optional[dict] = None):
        """
        分析情绪

        Returns:
            positive/neutral/negative
        """
        # 1. 优先检查 ASR 标签

        user_text, asr_labels = await self.qa_pairs_to_user_text_and_labels(qa_pairs)
        if "Qx:用户厌恶，骂脏话" in asr_labels:
            tag_label = "negative"
            tag_conf = 0.90
        elif any("不满意" in label for label in asr_labels):
            tag_label = "negative"
            tag_conf = 0.80
        elif any("满意" in label for label in asr_labels):
            tag_label = "positive"
            tag_conf = 0.80
        else:
            tag_label = "neutral"
            tag_conf = 0.30

        positive_count = 0
        negative_count = 0

        # 2. 检查 user_text
        for keyword in EMOTION_KEYWORDS['positive']:
            if keyword in user_text:
                positive_count += 1

        for keyword in EMOTION_KEYWORDS['negative']:
            if keyword in user_text:
                negative_count += 1

        # 负面优先（只要有负面词汇就倾向负面）
        if negative_count > 0:
            text_label = "negative"
            text_conf = min(0.80 + 0.02 * (negative_count - 1), 0.90)
        elif positive_count > 0:
            text_label = "positive"
            text_conf = min(0.80 + 0.02 * (positive_count - 1), 0.90)
        else:
            text_label = "neutral"
            text_conf = 0.30

        ##### 3. llm预测
        cleaned = []
        for record in qa_pairs:
            r = dict(record)
            r.pop("tags", None)
            cleaned.append(r)

        result_str = json.dumps(
            cleaned,
            ensure_ascii=False,
        )

        result = await self.llm_service.portrait_analysis_llm(result_str, portrait_label="emotion")
        logger.info(f"llm_result: {result}")
        llm_label = result.get("label")
        llm_conf = result.get("confidence", 0.0)

        #### 4. 语音文件情绪分析
        voice_up_label, voice_conf = await self.voice_analyze_emotion.analyze_call_emotion(voice_url)
        logger.info(f"voice_up_label: {voice_up_label};voice_conf:{voice_conf}")

        if voice_up_label == "POSITIVE":
            voice_label = "positive"
        elif voice_up_label == "NEGATIVE":
            voice_label = "negative"
        else:
            voice_label = "neutral"
            voice_conf = 0.0

        weights = weights or {"tag": 0.25, "text": 0.35, "llm": 0.20, "voice": 0.20}

        scores = {"negative": 0.0, "positive": 0.0}
        used = []

        if tag_label in ("negative", "positive") and tag_conf > 0 and weights["tag"] > 0:
            scores[tag_label] += weights["tag"] * tag_conf
            used.append({"label": tag_label, "confidence": tag_conf, "weight": weights["tag"]})

        if text_label in ("negative", "positive") and text_conf > 0 and weights["text"] > 0:
            scores[text_label] += weights["text"] * text_conf
            used.append({"label": text_label, "confidence": text_conf, "weight": weights["text"]})

        if llm_label in ("negative", "positive") and llm_conf > 0 and weights["llm"] > 0:
            scores[llm_label] += weights["llm"] * llm_conf
            used.append({"label": llm_label, "confidence": llm_conf, "weight": weights["llm"]})

        if voice_label in ("negative", "positive") and voice_conf > 0 and weights["voice"] > 0:
            scores[voice_label] += weights["voice"] * voice_conf
            used.append({"src": "voice", "label": voice_label, "confidence": voice_conf, "weight": weights["voice"]})

        # tie-break：若都为0，则无法判断
        if scores["positive"] == 0 and scores["negative"] == 0:
            return "neutral",llm_label, voice_up_label

        final_label = "positive" if scores["positive"] >= scores["negative"] else "negative"

        # 你也可以加一个“差值门槛”，差值太小就输出无法判断
        gap = abs(scores["positive"] - scores["negative"])
        if gap < 0.1:  # 可调
            return "neutral", llm_label, voice_up_label

        return final_label, llm_label, voice_up_label
    

    async def _analyze_complaint_risk(self,qa_pairs: list[dict],task_id: str, weights: Optional[dict] = None):
        """
        分析投诉风险
        
        Returns:
            high/medium/low
        """
        user_text, asr_labels = await self.qa_pairs_to_user_text_and_labels(qa_pairs)

        # 1. 优先检查 ASR 标签
        if "Qx:用户厌恶，骂脏话" in asr_labels:
            tag_label = "high"
            tag_conf = 0.90
        elif any("不满意" in label for label in asr_labels):
            tag_label = "high"
            tag_conf = 0.80
        elif any("满意" in label for label in asr_labels):
            tag_label = "low"
            tag_conf = 0.80
        else:
            tag_label = "medium"
            tag_conf = 0.30

        # 2. 检查用户不满意原因
        reason_label, reason_conf = None, 0.0
        if task_id in INSTALL_FINISH_TASKS:
            if ("Q5:客户评价标准与移动不一致" in asr_labels) or ("Q5-default:客户评价标准与移动不一致" in asr_labels):
                reason_label, reason_conf = "low", 0.80
            elif (("Q5:上网质量问题" in asr_labels) or ("Q5:非家庭网络类问题" in asr_labels) or ("Q5:装维服务不及时" in asr_labels) or ("Q5:装维服务不规范" in asr_labels)or ("Q5-default:上网质量问题" in asr_labels) or ("Q5-default:非家庭网络类问题" in asr_labels) or ("Q5-default:装维服务不及时" in asr_labels) or ("Q5-default:装维服务不规范" in asr_labels)):
                reason_label, reason_conf = "high", 0.80

        elif task_id in COMPLAINT_CLOSE_TASKS:
            if ("Q8:客户评价标准与移动不一致" in asr_labels) or ("Q8-default:客户评价标准与移动不一致" in asr_labels):
                reason_label, reason_conf = "low", 0.80
            elif (("Q8:上网质量问题" in asr_labels) or ("Q8:非家庭网络类问题" in asr_labels) or ("Q8:装维服务不及时" in asr_labels) or ("Q8:装维服务不规范" in asr_labels)or ("Q8-default:上网质量问题" in asr_labels) or ("Q8-default:非家庭网络类问题" in asr_labels) or ("Q8-default:装维服务不及时" in asr_labels) or ("Q8-default:装维服务不规范" in asr_labels)):
                reason_label, reason_conf = "high", 0.80

        elif task_id in QOE_VISIT_TASKS:
            if ("Q6:客户评价标准与移动不一致" in asr_labels) or ("Q6-default:客户评价标准与移动不一致" in asr_labels):
                reason_label, reason_conf = "low", 0.80
            elif (("Q6:上网质量问题" in asr_labels) or ("Q6:非家庭网络类问题" in asr_labels) or ("Q6:装维服务不及时" in asr_labels) or ("Q6:装维服务不规范" in asr_labels) or ("Q6:质差未处理报结" in asr_labels) or ("Q6-default:上网质量问题" in asr_labels) or ("Q6-default:非家庭网络类问题" in asr_labels) or ("Q6-default:装维服务不及时" in asr_labels) or ("Q6-default:装维服务不规范" in asr_labels) or ("Q6-default:质差未处理报结" in asr_labels)):
                reason_label, reason_conf = "high", 0.80
        else:
            reason_label, reason_conf = "medium", 0.30

        # 3. 检查 user_text
        high_count = 0
        medium_count = 0

        for keyword in COMPLAINT_KEYWORDS['high']:
            if keyword in user_text:
                high_count += 1

        for keyword in COMPLAINT_KEYWORDS['medium']:
            if keyword in user_text:
                medium_count += 1

        if high_count >= 1 or medium_count >= 3:
            text_label = "high"
            text_conf = min(0.80 + 0.02 * (high_count - 1), 0.90)
        elif medium_count >= 1 and medium_count < 3:
            text_label = "medium"
            text_conf = min(0.80 + 0.02 * (medium_count - 1), 0.90)
        else:
            text_label = "low"
            text_conf = 0.30

        ##### 4. llm预测
        cleaned = []
        for record in qa_pairs:
            r = dict(record)
            r.pop("tags", None)
            cleaned.append(r)

        result_str = json.dumps(
            cleaned,
            ensure_ascii=False,
        )
        result = await self.llm_service.portrait_analysis_llm(result_str, portrait_label="complaint")
        llm_label = result.get("label")
        llm_conf = result.get("confidence", 0.0)

        weights = weights or {"tag": 0.40, "reason": 0.20, "text": 0.25, "llm": 0.15}
        scores = {"high": 0.0, "medium": 0.0, "low": 0.0}
        used = []

        if tag_label in ("high", "medium", "low") and tag_conf > 0 and weights["tag"] > 0:
            scores[tag_label] += weights["tag"] * tag_conf
            used.append({"label": tag_label, "confidence": tag_conf, "weight": weights["tag"]})

        if reason_label in ("high", "medium", "low") and reason_conf > 0 and weights["reason"] > 0:
            scores[reason_label] += weights["reason"] * reason_conf
            used.append({"label": reason_label, "confidence": reason_conf, "weight": weights["reason"]})

        if text_label in ("high", "medium", "low") and text_conf > 0 and weights["text"] > 0:
            scores[text_label] += weights["text"] * text_conf
            used.append({"label": text_label, "confidence": text_conf, "weight": weights["text"]})

        if llm_label in ("high", "medium","low") and llm_conf > 0 and weights["llm"] > 0:
            scores[llm_label] += weights["llm"] * llm_conf
            used.append({"label": llm_label, "confidence": llm_conf, "weight": weights["llm"]})

        # tie-break：若都为0，则无法判断
        if max(scores.values()) == 0:
            return "medium", llm_label

        final_label = max(scores, key=scores.get)
        final_score = scores[final_label]

        # 你也可以加一个“差值门槛”，差值太小就输出无法判断
        # gap = abs(scores["medium"] - scores["high"])
        # if gap < 0.1:  # 可调
        #     return "medium", "asr_tag+score+llm"

        return final_label, llm_label
    
    async def _analyze_churn_risk(self,qa_pairs: list[dict], weights: Optional[dict] = None):
        """
        分析流失风险
        
        Returns:
            high/medium/low
        """
        user_text, asr_labels = await self.qa_pairs_to_user_text_and_labels(qa_pairs)

        ### 1. 检查user_text
        high_count = 0
        medium_count = 0

        for keyword in CHURN_KEYWORDS['high']:
            if keyword in user_text:
                high_count += 1

        for keyword in CHURN_KEYWORDS['medium']:
            if keyword in user_text:
                medium_count += 1

        if high_count >= 1 or medium_count >= 3:
            text_label = "high"
            text_conf = min(0.80 + 0.02 * (high_count - 1), 0.90)
        elif medium_count >= 1 and medium_count < 3:
            text_label = "medium"
            text_conf = min(0.80 + 0.02 * (medium_count - 1), 0.90)
        else:
            text_label = "low"
            text_conf = 0.30

        ##### 2. llm预测
        cleaned = []
        for record in qa_pairs:
            r = dict(record)
            r.pop("tags", None)
            cleaned.append(r)

        result_str = json.dumps(
            cleaned,
            ensure_ascii=False,
        )
        result = await self.llm_service.portrait_analysis_llm(result_str, portrait_label="churn")
        llm_label = result.get("label")
        llm_conf = result.get("confidence", 0.0)

        weights = weights or {"text": 0.6, "llm": 0.4}
        scores = {"high": 0.0, "medium": 0.0, "low": 0.0}
        used = []

        if text_label in ("high", "medium", "low") and text_conf > 0 and weights["text"] > 0:
            scores[text_label] += weights["text"] * text_conf
            used.append({"label": text_label, "confidence": text_conf, "weight": weights["text"]})

        if llm_label in ("high", "medium", "low") and llm_conf > 0 and weights["llm"] > 0:
            scores[llm_label] += weights["llm"] * llm_conf
            used.append({"label": llm_label, "confidence": llm_conf, "weight": weights["llm"]})

        # tie-break：若都为0，则无法判断
        if max(scores.values()) == 0:
            return "medium", llm_label

        final_label = max(scores, key=scores.get)
        final_score = scores[final_label]

        # 你也可以加一个“差值门槛”，差值太小就输出无法判断
        # gap = abs(scores["medium"] - scores["high"])
        # if gap < 0.1:  # 可调
        #     return "medium", "asr_tag+score+llm"

        return final_label, llm_label


    async def _analyze_willingness(self, duration: int, rounds: int) -> str:
        """
        分析沟通意愿
        
        基于通话时长和交互轮次判断
        
        Args:
            duration: 通话时长（秒）
            rounds: 交互轮次
            
        Returns:
            深度/一般/较低
        """
        # 深度：平均时长 > 60秒 或 轮次 > 5
        if duration > 60 or rounds > 5:
            return '深度'
        
        # 较低：时长 < 20秒 且 轮次 < 3
        if duration < 20 and rounds < 3:
            return '较低'
        
        return '一般'

    async def get_unsatisfied_reason(
        self,
        qa_pairs: list[dict],
        task_id: str,
        weights: Optional[dict] = None,
    ) -> Optional[str]:
        """
        基于 task_id + 指定问题(Q4/Q8/Q6 及 default)的 robot/custom 内容，
        让模型在限定集合内判断“不满意原因”。

        返回：
            候选原因字符串；若无需判断或信息不足返回 None
        """
        # 质差派单问卷：不需要
        print(f'task_id:{task_id}')
        if task_id in QOE_SURVEY_TASKS:
            return None

        # 不同任务对应的 question key & 候选集合
        if task_id in INSTALL_FINISH_TASKS:
            keys = ["Q5", "Q5-default"]
            candidates = ['装维服务不及时', '接通未评价', '客户评价标准与移动不一致', '非家庭网络类问题', '装维服务不规范', '上网质量问题']
        elif task_id in COMPLAINT_CLOSE_TASKS:
            keys = ["Q8", "Q8-default"]
            candidates = ['装维服务不及时', '接通未评价', '客户评价标准与移动不一致', '非家庭网络类问题', '装维服务不规范', '上网质量问题']
        elif task_id in QOE_VISIT_TASKS:
            keys = ["Q6", "Q6-default"]
            candidates = ['质差未处理报结', '装维服务不及时', '接通未评价', '客户评价标准与移动不一致', '非家庭网络类问题', '装维服务不规范', '上网质量问题']
        else:
            # 其他任务：不判断
            return None

        segs = await self._extract_question_qa_text(qa_pairs, keys)
   
        if not segs:
            return None

        seg_text = json.dumps(segs, ensure_ascii=False, indent=2)

        result = await self.llm_service.portrait_analysis_llm(seg_text, candidates, portrait_label="unsatisfied_reason")
        reason = result.get("reason")

        if reason == "接通未评价":
            return None

        if reason in candidates:
            return reason
        # 兜底：如果模型没按约束输出
        return None

    async def get_visit_and_reasoin(self, qa_pairs: list[dict]) -> dict:
        """
        两段式：
        1) 判定是否需要上门 visit_needed
        2) 若需要，判定上门原因 visit_reason（限定候选集合）
        """
        # 1) 清洗 tags，构建输入
        cleaned = []
        for record in qa_pairs:
            r = dict(record)
            r.pop("tags", None)
            cleaned.append(r)
        result_str = json.dumps(cleaned, ensure_ascii=False)

        # -------------------------
        # Step 1: 是否需要上门
        # -------------------------
        res_need = await self.llm_service.portrait_analysis_llm(
            result_str,
            portrait_label="visit_needed",
        )

        # 兼容不同返回：优先 visit_needed，其次 label
        visit_needed = (res_need.get("visit_needed") or res_need.get("label") or "").strip().lower()
        if visit_needed in ("yes", "y", "true", "1", "需要", "要", "需上门"):
            visit_needed = "yes"
        elif visit_needed in ("no", "n", "false", "0", "不需要", "无需", "不用"):
            visit_needed = "no"
        else:
            # 兜底：不确定时按 no（避免乱派单）
            visit_needed = "no"

        # 若不需要上门，直接返回
        if visit_needed == "no":
            return "no", None

        # -------------------------
        # Step 2: 上门原因（强约束）
        # -------------------------
        res_reason = await self.llm_service.portrait_analysis_llm(
            result_str,
            portrait_label="visit_reason",
        )

        visit_reason = (
                    res_reason.get("visit_reason") or res_reason.get("reason") or res_reason.get("label") or "").strip()

        return "yes", visit_reason

    async def _analyze_harassment_risk(self, qa_pairs: list[dict], weights: Optional[dict] = None):
        """
        分析是否防骚扰（用户是否表现出反感回访/骚扰意向）

        判断标准：
        - 是 (yes): 用户明确表达反感、拒绝继续通话、表示已多次被问、威胁投诉等
        - 否 (no): 无明显骚扰意向

        Returns:
            yes/no
        """
        user_text, asr_labels = await self.qa_pairs_to_user_text_and_labels(qa_pairs)

        if "Qx:用户厌恶，骂脏话" in asr_labels:
            return "yes", None

        ### 1. 检查 user_text (关键词匹配)
        high_count = 0
        for keyword in HARASSMENT_KEYWORDS['high']:
            if keyword in user_text:
                high_count += 1

        # 只要命中关键词，即判定为有骚扰风险
        if high_count >= 1:
            text_label = "yes"
            text_conf = min(0.85 + 0.03 * (high_count - 1), 0.95)
        else:
            text_label = "no"
            text_conf = 0.30

        ##### 2. llm预测
        cleaned = []
        for record in qa_pairs:
            r = dict(record)
            r.pop("tags", None)
            cleaned.append(r)
        result_str = json.dumps(
            cleaned,
            ensure_ascii=False,
        )
        # 调用 LLM 进行语义分析，判断是否有骚扰/反感意向
        result = await self.llm_service.portrait_analysis_llm(result_str, portrait_label="harassment")
        llm_label = result.get("label")  # 期望返回 "yes" 或 "no"
        llm_conf = result.get("confidence", 0.0)

        # 默认权重：文本规则为主 (60%)，LLM为辅 (40%)
        weights = weights or {"text": 0.6, "llm": 0.4}

        scores = {"yes": 0.0, "no": 0.0}
        used = []

        if text_label in ("yes", "no") and text_conf > 0 and weights["text"] > 0:
            scores[text_label] += weights["text"] * text_conf
            used.append({"label": text_label, "confidence": text_conf, "weight": weights["text"]})

        if llm_label in ("yes", "no") and llm_conf > 0 and weights["llm"] > 0:
            scores[llm_label] += weights["llm"] * llm_conf
            used.append({"label": llm_label, "confidence": llm_conf, "weight": weights["llm"]})

        # tie-break：若都为0，则默认为无骚扰风险
        if max(scores.values()) == 0:
            return "no", llm_label

        final_label = max(scores, key=scores.get)
        final_score = scores[final_label]

        # 可选：如果分值非常接近，可以设定阈值，但此处二分类通常直接取最大值
        return final_label, llm_label

    async def aggregate_multi_calls(
        self,
        call_results: list[dict],
    ) -> dict:
        """
        多通电话综合规则
        
        Args:
            call_results: 每通电话的分析结果列表
                [
                    {
                        'satisfaction': 'satisfied',
                        'emotion': 'positive',
                        'complaint_risk': 'low',
                        'churn_risk': 'low',
                        'duration': 120,
                        'rounds': 8,
                        'call_date': datetime,
                    },
                    ...
                ]
        
        Returns:
            综合结果
        """
        if not call_results:
            return {
                'satisfaction': None,
                'emotion': 'neutral',
                'complaint_risk': 'low',
                'churn_risk': 'low',
                'willingness': '一般',
            }
        
        # 按时间排序（最新在最后）
        sorted_calls = sorted(
            call_results,
            key=lambda x: x.get('call_date') or '',
        )
        
        # 1. 满意度：取最后一次有效评分
        satisfaction = None
        for call in reversed(sorted_calls):
            if call.get('satisfaction'):
                satisfaction = call['satisfaction']
                break
        
        # 2. 情绪：负面优先
        emotions = [c.get('emotion') for c in sorted_calls if c.get('emotion')]
        if 'negative' in emotions:
            emotion = 'negative'
        elif 'positive' in emotions:
            emotion = 'positive'
        else:
            emotion = 'neutral'
        
        # 3. 投诉风险：高优先
        complaint_risks = [c.get('complaint_risk', 'low') for c in sorted_calls]
        if 'high' in complaint_risks:
            complaint_risk = 'high'
        elif 'medium' in complaint_risks:
            complaint_risk = 'medium'
        else:
            complaint_risk = 'low'
        
        # 4. 流失风险：高优先
        churn_risks = [c.get('churn_risk', 'low') for c in sorted_calls]
        if 'high' in churn_risks:
            churn_risk = 'high'
        elif 'medium' in churn_risks:
            churn_risk = 'medium'
        else:
            churn_risk = 'low'
        
        # 5. 沟通意愿：基于平均时长和平均轮次
        total_duration = sum(c.get('duration', 0) for c in sorted_calls)
        total_rounds = sum(c.get('rounds', 0) for c in sorted_calls)
        avg_duration = total_duration / len(sorted_calls) if sorted_calls else 0
        avg_rounds = total_rounds / len(sorted_calls) if sorted_calls else 0
        willingness = await self._analyze_willingness(int(avg_duration), int(avg_rounds))
        
        # 6. 综合风险等级
        risk_level = await get_risk_level(complaint_risk, churn_risk)
        
        return {
            'satisfaction': satisfaction,
            'emotion': emotion,
            'complaint_risk': complaint_risk,
            'churn_risk': churn_risk,
            'willingness': willingness,
            'risk_level': risk_level,
        }


# 全局服务实例
rule_engine = RuleEngineService()
