import io
from flask import Blueprint, request, jsonify
from flask_restx import Namespace, Resource, reqparse
import pandas as pd
from werkzeug.datastructures import FileStorage
import uuid
import os

from modules.analysis.analysis_module import s3_file
from modules.openai.csv_agent_module import analyze_csv, analyze_csv_from_bytes
from modules.openai.insight_service_module import extract_insight_and_recommendation

# Blueprint와 Namespace 설정
openai_bp = Blueprint('openai', __name__, url_prefix='/openai')
openai_ns = Namespace('openai', description="OpenAI related APIs")

# 파일 업로드 파서 설정
analyze_parser = reqparse.RequestParser()
analyze_parser.add_argument(
    "filename", type=str, required=True, help="CSV 파일명 (필수)"
)

PROMPT_TEMPLATE = """
너는 숙련된 데이터 분석가야. 반드시 아래의 형식을 따라 답변하되, 각 항목은 단순한 수치 나열이 아니라 **데이터 기반의 통찰, 구조적 사고, 실천 가능한 전략 제안**을 담아야 해. 그리고 올해 데이터이니까 다음월까지의 데이터만 분석해줘.

형식:
Thought: (이 분석을 왜 시작했는지 명확한 동기를 서술해줘. 데이터에서 어떤 문제가 보였는지, 어떤 가설을 검증하고 싶은지 논리적으로 서술해.)
Action: python_repl_ast
Action Input: (문제를 파악하기 위한 분석 코드. 평균, 분포, 이상치 탐지, 그룹 간 비교, 상관분석, 시계열 분석 등 다양한 분석 접근을 시도해도 좋아.)
Observation: (단순히 수치를 적는 게 아니라, 그 결과가 데이터 맥락에서 어떤 의미를 가지는지 짧게 해석해줘. 예: "고요금제 이용자의 이탈률이 평균보다 1.5배 높음")
... (필요하면 반복)

Final Answer: 
요약: (이 데이터에서 가장 주목할 만한 핵심 특징을 한 문장으로 요약해. 수치 + 의미 + 대상 + 맥락이 들어가면 좋아. 예: "신규 고객 중 3개월 이상 사용한 이용자의 이탈률은 5%로 매우 낮음")
예측: (데이터의 흐름이나 패턴을 기반으로, 향후 이탈 가능성 또는 추세를 정량적으로 예측해줘. 추론 근거가 포함되어야 해. 예측되는 수치와 그에 대한 이유도 설명해줘)
인사이트:
1. (데이터를 통해 발견한 **정확하고 구체적인 인사이트**를 기술해. 예: “주말에만 접속하는 고객의 이탈률이 평일 사용자 대비 2배 높음”)
2. (숨어 있던 **패턴 또는 상관관계**를 밝혀줘. 예: “결제 실패 경험이 2회 이상인 고객의 이탈률이 45%에 달함”)
3. (데이터로는 직접 보이지 않지만, 합리적으로 추론 가능한 **숨겨진 요인**을 포착해줘. 예: “저활성 사용자 중 고객센터 문의 빈도가 높은 경우, 이탈 징후로 볼 수 있음”)

행동 추천:
(분석 기반으로 반드시 **실행 가능한 전략 3가지**를 아래와 같은 구성으로 제시해줘. 단순한 조언이 아니라 실제 기획에 활용될 수 있게 작성해.)

1. **전략 제목**: (예 — ‘고위험 고객 조기 케어 프로그램 도입’)  
   - **무엇을 해야 하나요?**: (데이터에서 이탈 위험군을 사전에 식별해 선제적 대응하세요.)  
   - **왜 해야 하나요?**: (예: 이탈 가능성이 높은 고객을 유지하는 것이 신규 확보보다 비용 효율이 높습니다.)  
   - **어떻게 하나요?**: (예: ‘최근 14일간 접속 0회 + 이전 이용 기간 1개월 미만’ 고객에게 리마인드 이메일 발송)

2. **전략 제목**:  
   - **무엇을 해야 하나요?**  
   - **왜 해야 하나요?**  
   - **어떻게 하나요?**

3. **전략 제목**:  
   - **무엇을 해야 하나요?**  
   - **왜 해야 하나요?**  
   - **어떻게 하나요?**

질문: {user_question}
"""


@openai_ns.route('/analyze')
class OpenaiAnalyze(Resource):
    @openai_ns.expect(analyze_parser)
    def post(self):
        """
        CSV 파일과 자연어 질문을 받아 분석 및 인사이트/추천을 반환하는 엔드포인트
        """
        args = analyze_parser.parse_args()
        filename = args["filename"]

        file_content = s3_file(filename)
        if not file_content:
            return {"error": "S3에서 파일을 불러올 수 없습니다."}, 500

        # if hasattr(file, 'content_length') and file.content_length > 10 * 1024 * 1024:
        #     return {"error": "파일 크기는 10MB를 초과할 수 없습니다."}, 400

        user_question = args.get("question") or '이 데이터에서 주요 인사이트와 행동 추천을 한국어로 알려줘'

        full_prompt = PROMPT_TEMPLATE.format(user_question=user_question)

        try:
            # 1. LangChain + OpenAI로 분석 (temperature=0 등 옵션은 analyze_csv 내부에서 적용)
            llm_response = analyze_csv_from_bytes(file_content, full_prompt)

            # 2. 인사이트 및 행동 추천 추출
            insight = extract_insight_and_recommendation(llm_response)

            print("인사이트:", insight)
            # 3. 결과 반환
            return {
                "summary": insight.summary,
                "prediction": insight.prediction,
                "recommendations": insight.recommendations
            }, 200
        except Exception as e:
            # 에러 발생 시 메시지 반환
            return {"error": "분석 중 오류가 발생했습니다." + str(e)}, 500