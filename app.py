from flask import Flask
from flask import Blueprint
from flask_restx import Api
# from resources.config.internal_local_db_config import  Config
from resources.config.internal_db_config import Config
from models import db

# Blueprints
from routes.dash_board_routes import dashboard_bp
from routes.info_db_routes import info_db_bp
from routes.info_column_routes import info_column_bp
from routes.analysis_routes import analysis_bp
from routes.segments_routes import segments_bp
from routes.openai_routes import openai_bp
# from routes.shap_route import shap_bp  # SHAP 관련 주석처리

# API Namespaces
from routes.analysis_routes import analysis_ns
from routes.dash_board_routes import dashboard_ns
from routes.info_db_routes import info_db_ns
from routes.info_column_routes import info_column_ns
from routes.openai_routes import openai_ns
# from routes.shap_route import shap_ns  # SHAP 관련 주석처리

app = Flask(__name__)
app.config.from_object(Config)

# 데이터베이스 초기화
db.init_app(app)

# API Blueprint 설정
api_bp = Blueprint('api', __name__, url_prefix='/python-api')  # 실제 API 경로를 '/python-api'로 설정

# Swagger UI는 '/docs'로 노출
api = Api(api_bp,
          title='Cohort Analysis API',
          version='2.0',
          description='Swagger for Cohort APIs Only',
          doc='/docs'  # Swagger UI는 '/docs' 경로로 설정
)

# Namespace 등록
api.add_namespace(info_db_ns)
api.add_namespace(info_column_ns)
api.add_namespace(analysis_ns)
api.add_namespace(dashboard_ns)
api.add_namespace(openai_ns)
# api.add_namespace(shap_ns)  # SHAP 관련 주석처리

# Blueprint 등록
app.register_blueprint(info_db_bp)
app.register_blueprint(info_column_bp)
app.register_blueprint(analysis_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(segments_bp)
app.register_blueprint(openai_bp)
# app.register_blueprint(shap_bp)  # SHAP 관련 주석처리

# API Blueprint 등록
app.register_blueprint(api_bp)

if __name__ == '__main__':
    app.run(port=5001, debug=True)
