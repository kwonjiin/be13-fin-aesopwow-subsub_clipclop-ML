from dataclasses import dataclass

@dataclass
class Insight:
    summary: str           # 분석 요약
    recommendations: list  # 행동 추천 리스트
    prediction: str        # 예측 결과
