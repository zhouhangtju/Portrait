import io
import json
import os
import re
import asyncio
import subprocess
import tempfile
import time
from collections import Counter
from typing import Optional, Tuple, List, Dict
from urllib.parse import urlparse, parse_qs, urlunparse

import requests
from loguru import logger
from concurrent.futures import ThreadPoolExecutor, as_completed


VOICE_VALID = {"HAPPY", "SAD", "ANGRY", "NEUTRAL", "FEARFUL", "DISGUSTED", "SURPRISED", "EMO_UNKNOWN"}

EMOTION_MAPPING = {
    "HAPPY": "POSITIVE",
    "SURPRISED": "POSITIVE",
    "SAD": "NEGATIVE",
    "ANGRY": "NEGATIVE",
    "FEARFUL": "NEGATIVE",
    "DISGUSTED": "NEGATIVE",
    "NEUTRAL": "NEUTRAL",
    "EMO_UNKNOWN": "NEUTRAL"
}


class VoiceEmotionService:
    def __init__(
        self,
        asr_url: str = "http://188.107.245.53:8088/transcribe",
        max_concurrent: int = 5,
        neg_ratio_threshold: float = 0.2,
    ):
        self.asr_url = asr_url
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self.neg_ratio_threshold = neg_ratio_threshold

    async def analyze_call_emotion(
        self,
        voice_url: List[str],
    ) -> Tuple[Optional[str], float]:
        """
        返回：(label, conf)
        label ∈ {NEUTRAL, POSITIVE, NEGATIVE, None}
        """
        if not voice_url:
            return None, 0.0

        # 在线程池跑阻塞 I/O
        futures = []
        for i, url in enumerate(voice_url):
            futures.append(self._executor.submit(self.process_one, url, f"call_{i:03d}"))
            time.sleep(0.1)

        results: List[Dict] = []
        labels: List[str] = []
        err_422 = 0

        for fut in as_completed(futures):
            r = fut.result()

            # 兼容性兜底：保证 r 是 dict
            if not isinstance(r, dict):
                r = {"session_id": None, "error": f"invalid_result_type:{type(r)}"}

            results.append(r)
            logger.info(f"[voice] session={r.get('session_id')} keys={list(r.keys())}")
            logger.info(f"[voice] text_head={str(r.get('text', ''))[:200]}")

            if r.get("http_status") == 422 or r.get("error") == "download_voice_422":
                err_422 += 1
                continue

            text = r.get("text", "") or ""
            tags = re.findall(r"<\|([^|]+)\|>", text)
            if len(tags) >= 2 and tags[1] in VOICE_VALID:
                # 将原始情绪标签映射到三大类
                original_label = tags[1]
                mapped_label = EMOTION_MAPPING.get(original_label, "NEUTRAL")
                labels.append(mapped_label)
                logger.info(f"[voice] 原始标签: {original_label} -> 映射到: {mapped_label}")

        # ✅ 如果所有 url 都是 422：返回 neutral, 0.3
        if err_422 == len(voice_url):
            return "NEUTRAL", 0.3

        label, conf = self.aggregate_call_emotion(labels)
        return label, conf

    def process_one(self, url: str, session_id: str) -> Dict:
        try:
            resp = requests.get(url, timeout=30)
            logger.info(f"voice_resp:{resp}; url:{url}")

            # 422：直接终止，不往下执行
            if resp.status_code == 422:
                return {
                    "session_id": session_id,
                    "url": url,
                    "error": "download_voice_422",
                    "http_status": 422,
                }

            resp.raise_for_status()

            content_type = resp.headers.get("Content-Type", "audio/wav")
            wav_bytes = resp.content

            audio_buffer = io.BytesIO(wav_bytes)
            audio_buffer.name = f"{session_id}.wav"

            return self.transcribe_audio_stream(
                session_id=session_id,
                audio_stream=audio_buffer,
                filename=audio_buffer.name,
                content_type=content_type,
            )

        except Exception as e:
            return {
                "session_id": session_id,
                "url": url,
                "error": str(e),
            }


    def transcribe_audio_stream(self, session_id: str, audio_stream, filename: str, content_type: str) -> Dict:
        start = time.time()

        files = {"audio": (filename, audio_stream, content_type or "application/octet-stream")}
        data = {"session_id": session_id, "format": "wav"}

        resp = requests.post(self.asr_url, files=files, data=data, timeout=120)
        resp.raise_for_status()
        result = resp.json()

        elapsed = time.time() - start
        logger.info(
            f"会话 {session_id} 完成，耗时: {elapsed:.2f}s, "
            f"conn={result.get('connection_id')}, "
            f"text={str(result.get('text',''))[:50]}"
        )
        return result

    def aggregate_call_emotion(
            self,
            labels: List[str],
            weights: Optional[Dict[str, float]] = None,
            min_votes: int = 1,
    ) -> Tuple[Optional[str], float]:
        """
        输入：多段标签列表
        输出：通话级最终标签 + 置信度

        约定：
        - EMO_UNKNOWN 在聚合阶段等价视为 NEUTRAL
        - 最终只输出 {NEGATIVE, POSITIVE, NEUTRAL} 或 (None, 0.0)
        """
        # 1) 过滤非法值 + 归一化 EMO_UNKNOWN -> NEUTRAL
        valid_labels = [x for x in labels if x in ("NEGATIVE", "POSITIVE", "NEUTRAL")]

        if len(valid_labels) < min_votes:
            return None, 0.0

        cnt = Counter(valid_labels)
        total = sum(cnt.values())

        # 2) 负面优先
        neg_ratio = cnt.get("NEGATIVE", 0) / total
        if neg_ratio >= self.neg_ratio_threshold:
            conf = min(0.70 + 0.30 * neg_ratio, 0.95)
            return "NEGATIVE", conf

        # 3) 加权投票（仅对三类有效标签）
        if weights is None:
            weights = {"NEGATIVE": 1.5, "POSITIVE": 1.2, "NEUTRAL": 1.0}

        keys = ("NEGATIVE", "POSITIVE", "NEUTRAL")
        scores = {k: cnt.get(k, 0) * weights.get(k, 1.0) for k in keys}
        best = max(scores, key=scores.get)

        # 4) conf：领先分差映射（保留你原来的思路）
        sorted_scores = sorted(scores.values(), reverse=True)
        gap = sorted_scores[0] - sorted_scores[1] if len(sorted_scores) >= 2 else sorted_scores[0]
        conf = min(0.60 + 0.10 * gap, 0.90)

        return best, conf


voice_emotion_service = VoiceEmotionService()
