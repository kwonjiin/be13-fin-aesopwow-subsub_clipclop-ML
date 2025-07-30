from models.insight import Insight
import re

def extract_insight_and_recommendation(llm_response: str) -> Insight:
    if not llm_response or not llm_response.strip():
        return Insight(summary="", prediction="", recommendations=[])

    lines = llm_response.splitlines()
    section = None
    summary = ""
    prediction = ""
    recommendations = []
    current_rec = ""

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith("요약:"):
            section = "summary"
            summary = line.replace("요약:", "").strip()

        elif line.startswith("예측:"):
            section = "prediction"
            prediction = line.replace("예측:", "").strip()

        elif line.startswith("인사이트:"):
            section = "insight"

        elif line.startswith("행동 추천:"):
            section = "recommendation"

        elif section == "insight" and re.match(r'^\d+\.', line):
            # 인사이트도 추천에 포함
            insight_text = line[line.find('.') + 1:].strip()
            recommendations.append(f"(인사이트) {insight_text}")

        elif section == "recommendation":
            if re.match(r'^\d+\.\s+\*\*(.*?)\*\*:', line):  # 예: 1. **데이터 검증 및 정제**:
                if current_rec:
                    recommendations.append(current_rec.strip())
                current_rec = line  # 새 제목 시작
            elif line.startswith('-'):
                current_rec += f"\n{line}"

    if current_rec:
        recommendations.append(current_rec.strip())

    return Insight(
        summary=summary,
        prediction=prediction,
        recommendations=recommendations
    )
