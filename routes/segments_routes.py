from flask import Blueprint, request, jsonify
import os
import io
from datetime import datetime
from flask import send_file, jsonify
import pandas as pd
from modules.common.user.user_utils import load_data
from modules.common.s3_client import get_s3_client, bucket_name
from modules.common.convert_data import convert_data

segments_bp = Blueprint('segments', __name__, url_prefix='/api/segment')

def upload_file_to_s3(file_path, s3_key):
    s3_client = get_s3_client()
    try:
        s3_client.upload_file(file_path, bucket_name, s3_key)
        print(f"{file_path} 파일이 S3에 성공적으로 업로드되었습니다. 위치: s3://{bucket_name}/{s3_key}")
    except Exception as e:
        print(f"S3 업로드 실패: {e}")
        raise

@segments_bp.route('/subscription', methods=['GET'])
def segment_subscription():
    info_db_no = request.args.get('info_db_no', type=int)
    user_info = request.args.get('user_info', type=str)
    user_sub_info = request.args.get('user_sub_info', type=str)
    target_column = 'subscription'

    if info_db_no is None or not user_info or not user_sub_info:
        return jsonify({"success": False, "message": "info_db_no, user_info, user_sub_info 파라미터가 필요합니다."}), 400

    try:
        df_user = convert_data(info_db_no, user_info)
        df_user = pd.DataFrame(df_user)
        df_sub = convert_data(info_db_no, user_sub_info)
        df_sub = pd.DataFrame(df_sub)
    except Exception as e:
        return jsonify({"success": False, "message": f"데이터 로드 중 오류: {str(e)}"}), 500

    if 'user_no' in df_user.columns:
        df_user.rename(columns={'user_no': 'user_id'}, inplace=True)
    if 'user_no' in df_sub.columns:
        df_sub.rename(columns={'user_no': 'user_id'}, inplace=True)

    user_columns = ['user_id', 'name', 'age', 'country', 'watch_time_hours', 'favorite_genre', 'last_login', 'gender']
    sub_columns = ['user_id', 'subscription_type', 'started_at']  # started_at을 날짜 기준으로 사용

    missing_user = [col for col in user_columns if col not in df_user.columns]
    missing_sub = [col for col in sub_columns if col not in df_sub.columns]
    if missing_user:
        return jsonify({"success": False, "message": f"df_user에 다음 컬럼이 없습니다: {missing_user}"}), 500
    if missing_sub:
        return jsonify({"success": False, "message": f"df_sub에 다음 컬럼이 없습니다: {missing_sub}"}), 500

    # 유저별 최신 구독 이력만 남기기 (started_at 기준)
    df_sub['started_at'] = pd.to_datetime(df_sub['started_at'], errors='coerce')
    df_sub = df_sub.sort_values(['user_id', 'started_at'], ascending=[True, False])
    df_sub_latest = df_sub.drop_duplicates(subset=['user_id'], keep='first')
    df_sub_latest = df_sub_latest[['user_id', 'subscription_type']]

    df_user = df_user[user_columns]
    df = pd.merge(df_user, df_sub_latest, on='user_id', how='left')

    now = datetime.now()
    now_str = now.strftime("%Y%m%d%H%M%S")

    def get_sub_segment(sub):
        if pd.isna(sub):
            return 'unknown'
        sub = str(sub).lower()
        if sub == 'basic':
            return 'Basic'
        elif sub == 'standard':
            return 'Standard'
        elif sub == 'premium':
            return 'Premium'
        else:
            return 'unknown'

    df['segment'] = df['subscription_type'].apply(get_sub_segment)

    # 로컬 파일 저장
    save_dir = "csv_exports"
    os.makedirs(save_dir, exist_ok=True)
    local_filename = f"{info_db_no}_segment_{target_column}_{now_str}.csv"
    file_path = os.path.join(save_dir, local_filename)

    final_columns = ['segment'] + user_columns + ['subscription_type']
    try:
        df.to_csv(file_path, columns=final_columns, index=False, encoding="utf-8")
    except Exception as e:
        return jsonify({"success": False, "message": f"CSV 저장 중 오류: {str(e)}"}), 500

    # S3 업로드 (경로 예시: info_db_no/segment/target_column/파일명)
    s3_key = f"{info_db_no}/segment/{target_column}/{local_filename}"
    try:
        upload_file_to_s3(file_path, s3_key)
    except Exception as e:
        return jsonify({"success": False, "message": f"S3 업로드 중 오류: {str(e)}"}), 500

    return jsonify({
        "success": True,
        "filename": local_filename,
        "s3_key": s3_key
    }), 200



@segments_bp.route('/watchtime', methods=['GET'])
def segment_watchtime():
    info_db_no = request.args.get('info_db_no', type=int)
    user_info = request.args.get('user_info', type=str)
    user_sub_info = request.args.get('user_sub_info', type=str)
    target_column = 'watch_time'

    if info_db_no is None or not user_info or not user_sub_info:
        return jsonify({"success": False, "message": "info_db_no, user_info, user_sub_info 파라미터가 필요합니다."}), 400

    try:
        df_user = convert_data(info_db_no, user_info)
        df_user = pd.DataFrame(df_user)
        df_sub = convert_data(info_db_no, user_sub_info)
        df_sub = pd.DataFrame(df_sub)
    except Exception as e:
        return jsonify({"success": False, "message": f"데이터 로드 중 오류: {str(e)}"}), 500

    # if 'user_no' in df_user.columns:
    #     df_user.rename(columns={'user_no': 'user_id'}, inplace=True)
    # if 'user_no' in df_sub.columns:
    #     df_sub.rename(columns={'user_no': 'user_id'}, inplace=True)

    user_columns = ['user_id', 'name', 'age', 'country', 'watch_time_hours', 'favorite_genre', 'last_login', 'gender']
    sub_columns = ['user_id', 'subscription_type', 'started_at']  # started_at을 날짜 기준으로 사용

    missing_user = [col for col in user_columns if col not in df_user.columns]
    missing_sub = [col for col in sub_columns if col not in df_sub.columns]
    if len(missing_user) > 0:
        return jsonify({"success": False, "message": f"df_user에 다음 컬럼이 없습니다: {missing_user}"}), 500
    if len(missing_sub) > 0:
        return jsonify({"success": False, "message": f"df_sub에 다음 컬럼이 없습니다: {missing_sub}"}), 500

    # 유저별 최신 구독 이력만 남기기 (started_at 기준)
    df_sub['started_at'] = pd.to_datetime(df_sub['started_at'], errors='coerce')
    df_sub = df_sub.sort_values(['user_id', 'started_at'], ascending=[True, False])
    df_sub_latest = df_sub.drop_duplicates(subset=['user_id'], keep='first')
    df_sub_latest = df_sub_latest[['user_id', 'subscription_type']]

    df_user = df_user[user_columns]
    df = pd.merge(df_user, df_sub_latest, on='user_id', how='left')

    # 컬럼명 확인 및 방어코드 추가
    if 'watch_time_hours' not in df.columns:
        return jsonify({"success": False, "message": "'watch_time_hours' 컬럼이 데이터에 없습니다."}), 500

    def get_watch_time_segment(hour):
        if pd.isna(hour):
            return 'unknown'
        if hour < 30:
            return 'Light User'
        elif hour < 60:
            return 'Core User'
        else:
            return 'Power User'

    df['segment'] = df['watch_time_hours'].apply(get_watch_time_segment)

    # 로컬 파일 저장
    save_dir = "csv_exports"
    os.makedirs(save_dir, exist_ok=True)
    now = datetime.now()
    now_str = now.strftime("%Y%m%d%H%M%S")
    local_filename = f"{info_db_no}_segment_{target_column}_{now_str}.csv"
    file_path = os.path.join(save_dir, local_filename)

    final_columns = ['segment'] + user_columns + ['subscription_type']
    try:
        df.to_csv(file_path, columns=final_columns, index=False, encoding="utf-8")
    except Exception as e:
        return jsonify({"success": False, "message": f"CSV 저장 중 오류: {str(e)}"}), 500

    # S3 업로드
    s3_key = f"{info_db_no}/segment/{target_column}/{local_filename}"
    try:
        upload_file_to_s3(file_path, s3_key)
    except Exception as e:
        return jsonify({"success": False, "message": f"S3 업로드 중 오류: {str(e)}"}), 500

    return jsonify({
        "success": True,
        "filename": local_filename,
        "s3_key": s3_key
    }), 200



@segments_bp.route('/lastlogin', methods=['GET'])
def segment_lastlogin():
    info_db_no = request.args.get('info_db_no', type=int)
    user_info = request.args.get('user_info', type=str)
    user_sub_info = request.args.get('user_sub_info', type=str)
    target_column = 'last_login'

    if info_db_no is None or not user_info or not user_sub_info:
        return jsonify({"success": False, "message": "info_db_no, user_info, user_sub_info 파라미터가 필요합니다."}), 400

    try:
        df_user = convert_data(info_db_no, user_info)
        df_user = pd.DataFrame(df_user)
        df_sub = convert_data(info_db_no, user_sub_info)
        df_sub = pd.DataFrame(df_sub)
    except Exception as e:
        return jsonify({"success": False, "message": f"데이터 로드 중 오류: {str(e)}"}), 500

    # user_no 컬럼명 통일
    if 'user_id' in df_user.columns:
        df_user.rename(columns={'user_no': 'user_id'}, inplace=True)
    if 'user_no' in df_sub.columns:
        df_sub.rename(columns={'user_no': 'user_id'}, inplace=True)

    user_columns = ['user_id', 'name', 'age', 'country', 'watch_time_hours', 'favorite_genre', 'last_login', 'gender']
    sub_columns = ['user_id', 'subscription_type', 'started_at']  # started_at을 날짜 기준으로 사용

    missing_user = [col for col in user_columns if col not in df_user.columns]
    missing_sub = [col for col in sub_columns if col not in df_sub.columns]
    if missing_user:
        return jsonify({"success": False, "message": f"df_user에 다음 컬럼이 없습니다: {missing_user}"}), 500
    if missing_sub:
        return jsonify({"success": False, "message": f"df_sub에 다음 컬럼이 없습니다: {missing_sub}"}), 500

    # 유저별 최신 구독 이력만 남기기 (started_at 기준)
    df_sub['started_at'] = pd.to_datetime(df_sub['started_at'], errors='coerce')
    df_sub = df_sub.sort_values(['user_id', 'started_at'], ascending=[True, False])
    df_sub_latest = df_sub.drop_duplicates(subset=['user_id'], keep='first')
    df_sub_latest = df_sub_latest[['user_id', 'subscription_type']]

    df_user = df_user[user_columns]
    df = pd.merge(df_user, df_sub_latest, on='user_id', how='left')

    now = datetime.now()
    now_str = now.strftime("%Y%m%d%H%M%S")

    def get_login_segment(last_login):
        if pd.isna(last_login):
            return 'unknown'
        if isinstance(last_login, str):
            try:
                last_login_dt = datetime.strptime(last_login, "%Y-%m-%d")
            except Exception:
                return 'unknown'
        else:
            last_login_dt = last_login
        diff = (now - last_login_dt).days
        if diff <= 30:
            return 'Frequent User'
        elif diff <= 60:
            return 'Dormant User'
        else:
            return 'Forgotten User'

    df['segment'] = df['last_login'].apply(get_login_segment)

    # 로컬 파일 저장
    save_dir = "csv_exports"
    os.makedirs(save_dir, exist_ok=True)
    local_filename = f"{info_db_no}_segment_{target_column}_{now_str}.csv"
    file_path = os.path.join(save_dir, local_filename)

    final_columns = ['segment'] + user_columns + ['subscription_type']
    try:
        df.to_csv(file_path, columns=final_columns, index=False, encoding="utf-8")
    except Exception as e:
        return jsonify({"success": False, "message": f"CSV 저장 중 오류: {str(e)}"}), 500

    # S3 업로드 (경로 예시: info_db_no/segment/target_column/파일명)
    s3_key = f"{info_db_no}/segment/{target_column}/{local_filename}"
    try:
        upload_file_to_s3(file_path, s3_key)
    except Exception as e:
        return jsonify({"success": False, "message": f"S3 업로드 중 오류: {str(e)}"}), 500

    return jsonify({
        "success": True,
        "filename": local_filename,
        "s3_key": s3_key
    }), 200



@segments_bp.route('/genre', methods=['GET'])
def segment_genre():
    info_db_no = request.args.get('info_db_no', type=int)
    user_info = request.args.get('user_info', type=str)
    user_sub_info = request.args.get('user_sub_info', type=str)
    target_column = 'favorite_genre'

    if info_db_no is None or not user_info or not user_sub_info:
        return jsonify({
            "success": False,
            "message": "info_db_no, user_info, user_sub_info 파라미터가 필요합니다."
        }), 400

    try:
        df_user = convert_data(info_db_no, user_info)
        df_user = pd.DataFrame(df_user)
        df_sub = convert_data(info_db_no, user_sub_info)
        df_sub = pd.DataFrame(df_sub)
    except Exception as e:
        return jsonify({"success": False, "message": f"데이터 로드 중 오류: {str(e)}"}), 500

    # user_no → user_id 통일
    if 'user_no' in df_user.columns:
        df_user.rename(columns={'user_no': 'user_id'}, inplace=True)
    if 'user_no' in df_sub.columns:
        df_sub.rename(columns={'user_no': 'user_id'}, inplace=True)

    # 필요한 컬럼 정의
    user_columns = ['user_id', 'name', 'age', 'country', 'watch_time_hours', 'favorite_genre', 'last_login', 'gender']
    sub_columns = ['user_id', 'subscription_type', 'started_at']  # started_at을 날짜 기준으로 사용

    missing_user = [col for col in user_columns if col not in df_user.columns]
    missing_sub = [col for col in sub_columns if col not in df_sub.columns]

    if missing_user:
        return jsonify({"success": False, "message": f"df_user에 다음 컬럼이 없습니다: {missing_user}"}), 500
    if missing_sub:
        return jsonify({"success": False, "message": f"df_sub에 다음 컬럼이 없습니다: {missing_sub}"}), 500

    # 유저별 최신 구독 이력만 남기기 (started_at 기준)
    df_sub['started_at'] = pd.to_datetime(df_sub['started_at'], errors='coerce')
    df_sub = df_sub.sort_values(['user_id', 'started_at'], ascending=[True, False])
    df_sub_latest = df_sub.drop_duplicates(subset=['user_id'], keep='first')
    df_sub_latest = df_sub_latest[['user_id', 'subscription_type']]

    # 병합
    df_user = df_user[user_columns]
    df = pd.merge(df_user, df_sub_latest, on='user_id', how='left')

    # 세그먼트 컬럼 생성
    now = datetime.now().strftime("%Y%m%d%H%M%S")
    df['segment'] = df[target_column].fillna('unknown').astype(str)

    final_columns = ['segment'] + user_columns + ['subscription_type']

    # CSV 로컬 저장
    save_dir = "csv_exports"
    filename = f"{info_db_no}_segment_{target_column}_{now}.csv"
    os.makedirs(save_dir, exist_ok=True)
    file_path = os.path.join(save_dir, filename)

    try:
        df.to_csv(file_path, columns=final_columns, index=False, encoding="utf-8")
    except Exception as e:
        return jsonify({"success": False, "message": f"CSV 저장 중 오류: {str(e)}"}), 500

    # S3 업로드
    s3_key = f"{info_db_no}/segment/{target_column}/{filename}"
    try:
        upload_file_to_s3(file_path, s3_key)
    except Exception as e:
        return jsonify({"success": False, "message": f"S3 업로드 중 오류: {str(e)}"}), 500

    return jsonify({"success": True, "filename": filename, "s3_key": s3_key}), 200




@segments_bp.route('/list', methods=['GET'])
def segment_file_list():
    info_db_no = request.args.get('info_db_no', type=int)
    target_column = request.args.get('target_column', type=str)

    if not info_db_no or not target_column:
        return jsonify({'files': []}), 400

    prefix = f"{info_db_no}/segment/{target_column}/"
    s3_client = get_s3_client()

    try:
        file_keys = []
        continuation_token = None
        while True:
            if continuation_token:
                response = s3_client.list_objects_v2(
                    Bucket=bucket_name, Prefix=prefix, ContinuationToken=continuation_token
                )
            else:
                response = s3_client.list_objects_v2(
                    Bucket=bucket_name, Prefix=prefix
                )
            for obj in response.get('Contents', []):
                key = obj['Key']
                if key.endswith('.csv'):
                    file_keys.append(key)
            if response.get('IsTruncated'):
                continuation_token = response.get('NextContinuationToken')
            else:
                break
    except Exception as e:
        return jsonify({'files': []}), 500

    file_keys.sort(reverse=True)
    return jsonify({'files': file_keys})

@segments_bp.route('/list/<path:s3_key>', methods=['GET'])
def get_segment_csv(s3_key):
    s3_client = get_s3_client()
    try:
        obj = s3_client.get_object(Bucket=bucket_name, Key=s3_key)
        file_stream = io.BytesIO(obj['Body'].read())
        filename = s3_key.split('/')[-1]
        return send_file(
            file_stream,
            mimetype='text/csv',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        print(f"[ERROR] 파일 다운로드 실패: {e}")  # 에러 로그 추가!
        return jsonify({"success": False, "message": f"파일 다운로드 실패: {str(e)}"}), 500
