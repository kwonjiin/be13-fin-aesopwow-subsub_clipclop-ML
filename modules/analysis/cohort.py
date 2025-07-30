from collections import defaultdict
import csv
from datetime import datetime, timedelta
import io
from flask import jsonify, send_file
from sqlalchemy.orm import sessionmaker
from sqlalchemy import and_, create_engine, MetaData, Table, extract, func, select

from modules.analysis.analysis_module import save_FavGenre_csv_to_s3, save_LastLogin_csv_to_s3, save_SubscriptionType_csv_to_s3, save_pcl_csv_to_s3
from modules.info_db.info_db_module import get_info_db_by_info_db_no
from modules.info_column.info_column_module import get_info_columns_by_info_db_no_origin_table

def calculate_monthly_retention(user_ids, user_month_data):
    retention_rates = {}
    initial_user_count = len(user_ids)
    
    if initial_user_count == 0:
        return {month: 0.0 for month in range(1, 13)}
    
    for month in range(1, 13):
        alive_users = sum(
            1 for user_id in user_ids
            if (user_month_data.get(user_id, {}).get(month) or 0) > 0
        )
        retention_rates[month] = round(alive_users / initial_user_count, 2)

    return retention_rates

def calculate_monthly_retention_by_churn(total_users, churned_users_by_month):
    retention = {}
    remaining_users = total_users
    for month in range(1, 13):
        churned = churned_users_by_month.get(month, 0)

        if total_users == 0:
            retention_rate = 0
        else:
            retention_rate = (remaining_users / total_users) * 100
            if remaining_users < 0:
                remaining_users = 0
                retention_rate = 0

        retention[month] = round(retention_rate, 2)
        remaining_users -= churned

        if remaining_users < 0:
            remaining_users = 0

    return retention

def test_convert_data(info_db_no, origin_table):

    info_db = get_info_db_by_info_db_no(info_db_no).to_dict()
    user = info_db.get('user')
    host = info_db.get('host')
    password = info_db.get('password')
    port = info_db.get('port')
    name = info_db.get('name')

    if not info_db:
        return None
    else:
        engine = create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}")

        info_columns = get_info_columns_by_info_db_no_origin_table(info_db_no, origin_table)

        mapped_columns = {}

        for col in info_columns:
            mapped_columns[col.origin_column] = col.analysis_column

        metadata = MetaData()

        external_table = Table(origin_table, metadata, autoload_with=engine)

        with engine.connect() as conn:
            query = select(external_table)
            result = conn.execute(query).mappings().all()

            mapped_result = [
                {mapped_columns.get(k, k): v for k, v in row.items()}
                for row in result
            ]

        print(mapped_result)
        return mapped_result
    
def get_user_info_by_year(info_db_no, origin_table, year):

    info_db = get_info_db_by_info_db_no(info_db_no).to_dict()
    user = info_db.get('user')
    host = info_db.get('host')
    password = info_db.get('password')
    port = info_db.get('port')
    name = info_db.get('name')

    if not info_db:
        return None
    else:
        engine = create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}")

        info_columns = get_info_columns_by_info_db_no_origin_table(info_db_no, origin_table)

        mapped_columns = {}

        for col in info_columns:
            mapped_columns[col.origin_column] = col.analysis_column

        metadata = MetaData()

        external_table = Table(origin_table, metadata, autoload_with=engine)

        with engine.connect() as conn:
            query = select(external_table)
            result = conn.execute(query).mappings().all()

            mapped_result = [
                {mapped_columns.get(k, k): v for k, v in row.items()}
                for row in result
            ]

        print(mapped_result)
        return mapped_result
    
def analysis_cohort_PCL(info_db_no, target_table, target_date):
    target_month = target_date.month

    start_date = f"{target_date.year}-{target_date.month:02d}-01"
    if target_month == 12:
        end_date = f"{target_date.year + 1}-01-01"
    else:
        end_date = f"{target_date.year}-{target_date.month + 1:02d}-01"

    info_db = get_info_db_by_info_db_no(info_db_no).to_dict()
    if not info_db:
        return None

    user, host, password, port, name = (
        info_db.get('user'),
        info_db.get('host'),
        info_db.get('password'),
        info_db.get('port'),
        info_db.get('name'),
    )

    engine = create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}")
    target_table_columns = get_info_columns_by_info_db_no_origin_table(info_db_no, target_table)
    target_table_mapped_columns = {col.origin_column: col.analysis_column for col in target_table_columns}
    origin_mapped_columns = {col.analysis_column: col.origin_column for col in target_table_columns}

    metadata = MetaData()
    target_table_external_table = Table(target_table, metadata, autoload_with=engine)

    with engine.connect() as conn:
        ended_at = getattr(target_table_external_table.c, origin_mapped_columns.get('ended_at'))
        user_id = getattr(target_table_external_table.c, origin_mapped_columns.get('user_id'))
        watch_time_hour = getattr(target_table_external_table.c, origin_mapped_columns.get('watch_time_hour'))

        target_users_query = (
            select(user_id)
            .where(
                and_(
                    ended_at >= start_date,
                    ended_at < end_date,
                    extract('month', ended_at) == target_month
                )
            )
            .group_by(user_id)
        )
        result = conn.execute(target_users_query).mappings().all()
        key_name = list(result[0].keys())[0] if result else None
        target_user_ids = [user[key_name] for user in result]

        if target_user_ids:
            next_year = target_date.year + 1
            query = (
                select(
                    user_id,
                    extract('month', ended_at).label('month'),
                    extract('year', ended_at).label('year'),
                    watch_time_hour
                )
                .where(
                    and_(
                        ended_at >= start_date,
                        ended_at < f"{next_year}-{target_month:02d}-01",
                        user_id.in_(target_user_ids)
                    )
                )
                .group_by(
                    user_id,
                    extract('year', ended_at),
                    extract('month', ended_at)
                )
                .order_by(user_id, 'year', 'month')
            )
            result = conn.execute(query).mappings().all()

        target_table_mapped_result = [
            {target_table_mapped_columns.get(k, k): v for k, v in row.items()}
            for row in result
        ]

        user_month_data = defaultdict(lambda: {m: None for m in range(1, 13)})
        month_offset = target_month - 1

        for row in target_table_mapped_result:
            user_id = row['user_id']
            year_val = int(row['year'])
            month_val = int(row['month'])
            adjusted_month = (month_val - month_offset - 1) % 12 + 1
            watch_time_hour = row['watch_time_hour'] if row['watch_time_hour'] is not None else 0
            user_month_data[user_id][adjusted_month] = watch_time_hour

    result = {user_id: dict(monthly_data) for user_id, monthly_data in user_month_data.items()}
    user_category = {}
    p_users, c_users, l_users = [], [], []

    for user_id, monthly_data in user_month_data.items():
        first_month_hours = monthly_data.get(1) or 0
        if first_month_hours >= 60:
            user_category[user_id] = 'P'
            p_users.append(user_id)
        elif first_month_hours >= 30:
            user_category[user_id] = 'C'
            c_users.append(user_id)
        else:
            user_category[user_id] = 'L'
            l_users.append(user_id)

    monthly_dropout_counts = {month: {'P': 0, 'C': 0, 'L': 0} for month in range(1, 13)}

    for month in range(1, 13):
        for user_id, monthly_data in user_month_data.items():
            watch_time = monthly_data.get(month)
            if watch_time is None:
                group = user_category.get(user_id)
                if group:
                    monthly_dropout_counts[month][group] += 1

    group_total_counts = {
        'P': len(p_users),
        'C': len(c_users),
        'L': len(l_users)
    }

    p_retention = calculate_monthly_retention_by_churn(group_total_counts['P'], {m: monthly_dropout_counts[m]['P'] for m in range(1, 13)})
    c_retention = calculate_monthly_retention_by_churn(group_total_counts['C'], {m: monthly_dropout_counts[m]['C'] for m in range(1, 13)})
    l_retention = calculate_monthly_retention_by_churn(group_total_counts['L'], {m: monthly_dropout_counts[m]['L'] for m in range(1, 13)})

    try:
        save_pcl_csv_to_s3(info_db_no, p_retention, c_retention, l_retention)
        return jsonify({
            "success": True,
            "message": "CSV 파일이 S3에 저장되었습니다.",
        }), 200
    except Exception as e:
        print(f"CSV 저장 중 오류 발생: {e}")
        return jsonify({"success": False, "error": str(e)}), 500



def analysis_cohort_SubscriptionType(info_db_no, target_table, target_date):
    info_db = get_info_db_by_info_db_no(info_db_no).to_dict()
    user = info_db.get('user')
    host = info_db.get('host')
    password = info_db.get('password')
    port = info_db.get('port')
    name = info_db.get('name')

    if not info_db:
        return None
    else:
        engine = create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}")

        # Get user sub info columns
        target_table_columns = get_info_columns_by_info_db_no_origin_table(info_db_no, target_table)
        target_table_mapped_columns = {col.origin_column: col.analysis_column for col in target_table_columns}
        origin_mapped_columns = {col.analysis_column: col.origin_column for col in target_table_columns}

        metadata = MetaData()
        target_table_external_table = Table(target_table, metadata, autoload_with=engine)

        with engine.connect() as conn:
            ended_at = getattr(target_table_external_table.c, origin_mapped_columns.get('ended_at'))
            user_id = getattr(target_table_external_table.c, origin_mapped_columns.get('user_id'))
            subscription_type = getattr(target_table_external_table.c, origin_mapped_columns.get('subscription_type'))

            # target_date로부터 연, 월 추출
            year = target_date.year
            month = target_date.month

            # 1년치 시작/끝 날짜 계산
            start_date = f"{year}-{month:02d}-01"
            end_year = year + 1 if month != 1 else year
            end_month = (month - 1) or 12  # 0월 방지
            end_date = f"{end_year}-{end_month:02d}-01"

            # 첫 달 활동 사용자만 뽑기
            target_users_query = (
                select(user_id)
                .where(
                    and_(
                        ended_at >= start_date,
                        ended_at < end_date,
                        extract('month', ended_at) == month
                    )
                )
                .group_by(user_id)
            )
            result = conn.execute(target_users_query).mappings().all()

            key_name = list(result[0].keys())[0] if result else None
            target_user_ids = [user[key_name] for user in result]

            # 전체 1년치 데이터 가져오기
            if target_user_ids:
                query = (
                    select(
                        user_id,
                        extract('month', ended_at).label('month'),
                        extract('year', ended_at).label('year'),
                        subscription_type
                    )
                    .where(
                        and_(
                            ended_at >= start_date,
                            ended_at < end_date,
                            user_id.in_(target_user_ids)
                        )
                    )
                    .group_by(
                        user_id,
                        extract('year', ended_at),
                        extract('month', ended_at)
                    )
                    .order_by(user_id, 'year', 'month')
                )
                result = conn.execute(query).mappings().all()

            target_table_mapped_result = [
                {target_table_mapped_columns.get(k, k): v for k, v in row.items()}
                for row in result
            ]

            # 월 단위로 처리 (연도별로 월을 1~12로 보정)
            user_month_data = defaultdict(lambda: {m: None for m in range(1, 13)})
            month_offset = month - 1

            for row in target_table_mapped_result:
                user_id = row['user_id']
                year_val = int(row['year'])
                month_val = int(row['month'])
                adjusted_month = (month_val - month_offset - 1) % 12 + 1
                subscription_type = row['subscription_type'] if row['subscription_type'] is not None else None
                user_month_data[user_id][adjusted_month] = subscription_type

        result = {user_id: dict(monthly_data) for user_id, monthly_data in user_month_data.items()}

        # 사용자별로 첫달 사용시간에 따라 분류
        user_category = {}
        premium_users, standard_users, basic_users = [], [], []

        for user_id, monthly_data in user_month_data.items():
            first_month_subscription_type = monthly_data.get(1)
            if first_month_subscription_type == 'PREMIUM':
                user_category[user_id] = 'PREMIUM'
                premium_users.append(user_id)
            elif first_month_subscription_type == 'STANDARD':
                user_category[user_id] = 'STANDARD'
                standard_users.append(user_id)
            elif first_month_subscription_type == 'BASIC':
                user_category[user_id] = 'BASIC'
                basic_users.append(user_id)

        monthly_dropout_counts = {month: {'PREMIUM': 0, 'STANDARD': 0, 'BASIC': 0} for month in range(1, 13)}

        for month in range(1, 13):
            for user_id, monthly_data in user_month_data.items():
                subscription_type = monthly_data.get(month)
                if subscription_type is None:
                    group = user_category.get(user_id)
                    if group:
                        monthly_dropout_counts[month][group] += 1

        group_total_counts = {
            'PREMIUM': len(premium_users),
            'STANDARD': len(standard_users),
            'BASIC': len(basic_users)
        }

        premium_retention = calculate_monthly_retention_by_churn(group_total_counts['PREMIUM'], {m: monthly_dropout_counts[m]['PREMIUM'] for m in range(1, 13)})
        standard_retention = calculate_monthly_retention_by_churn(group_total_counts['STANDARD'], {m: monthly_dropout_counts[m]['STANDARD'] for m in range(1, 13)})
        basic_retention = calculate_monthly_retention_by_churn(group_total_counts['BASIC'], {m: monthly_dropout_counts[m]['BASIC'] for m in range(1, 13)})

        try:
            save_SubscriptionType_csv_to_s3(info_db_no, premium_retention, standard_retention, basic_retention)
            return jsonify({
                "success": True,
                "message": "CSV 파일이 S3에 저장되었습니다.",
            }), 200
        except Exception as e:
            print(f"CSV 저장 중 오류 발생: {e}")
            return jsonify({"success": False, "error": str(e)}), 500


def analysis_cohort_FavGenre(info_db_no, target_table_user, target_table_sub, target_date):
    info_db = get_info_db_by_info_db_no(info_db_no).to_dict()
    if not info_db:
        return jsonify({"success": False, "message": "DB 정보를 찾을 수 없습니다."}), 404

    user = info_db.get('user')
    host = info_db.get('host')
    password = info_db.get('password')
    port = info_db.get('port')
    name = info_db.get('name')

    engine = create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}")
    metadata = MetaData()

    # 날짜 처리
    # start_date = datetime.strptime(target_date, "%Y-%m-%d")
    start_date = target_date
    target_year = start_date.year
    target_month = start_date.month

    # 1년 후 같은 달의 1일
    try:
        end_date = start_date.replace(year=start_date.year + 1)
    except ValueError:
        end_date = start_date + timedelta(days=365)

    # 테이블 컬럼 매핑
    user_sub_table_columns = get_info_columns_by_info_db_no_origin_table(info_db_no, target_table_sub)
    user_table_columns = get_info_columns_by_info_db_no_origin_table(info_db_no, target_table_user)

    sub_origin_map = {col.analysis_column: col.origin_column for col in user_sub_table_columns}
    user_origin_map = {col.analysis_column: col.origin_column for col in user_table_columns}

    user_sub_table = Table(target_table_sub, metadata, autoload_with=engine)
    user_table = Table(target_table_user, metadata, autoload_with=engine)

    # user_sub_info의 user_id 컬럼 가져오기
    user_id_col_sub = getattr(user_sub_table.c, sub_origin_map['user_id'])
    ended_at_col_sub = getattr(user_sub_table.c, sub_origin_map['ended_at'])

    # user_info의 컬럼
    user_id_col_user = getattr(user_table.c, user_origin_map['user_id'])
    favorite_genre_col_user = getattr(user_table.c, user_origin_map['favorite_genre'])

    genre_list = ['Comedy', 'Horror', 'Drama', 'Romance', 'Action', 'Documentary', 'Sci-Fi']

    # 결과 딕셔너리: {장르: {월: 사용자수}}
    genre_monthly_counts = {genre: defaultdict(int) for genre in genre_list}

    with engine.connect() as conn:
        for genre in genre_list:
            first_month_user_query = (
                select(user_id_col_sub)
                .where(
                    extract('year', ended_at_col_sub) == target_year,
                    extract('month', ended_at_col_sub) == target_month
                )
                .distinct()
            )
            first_month_user_ids = conn.execute(first_month_user_query).scalars().all()
            if not first_month_user_ids:
                continue

            genre_user_query = (
                select(user_id_col_user)
                .where(
                    user_id_col_user.in_(first_month_user_ids),
                    favorite_genre_col_user == genre
                )
                .distinct()
            )
            genre_user_ids = conn.execute(genre_user_query).scalars().all()
            if not genre_user_ids:
                continue

            monthly_count_query = (
                select(
                    extract('year', ended_at_col_sub).label('year'),
                    extract('month', ended_at_col_sub).label('month'),
                    func.count(func.distinct(user_id_col_sub)).label('user_count')
                )
                .select_from(
                    user_sub_table.join(
                        user_table,
                        user_id_col_sub == user_id_col_user
                    )
                )
                .where(
                    and_(
                        ended_at_col_sub >= start_date,
                        ended_at_col_sub < end_date,
                        user_id_col_sub.in_(first_month_user_ids),
                        favorite_genre_col_user == genre
                    )
                )
                .group_by(extract('year', ended_at_col_sub), extract('month', ended_at_col_sub))
                .order_by('year', 'month')
            )

            monthly_results = conn.execute(monthly_count_query).mappings().all()

            for row in monthly_results:
                year, month, count = int(row['year']), int(row['month']), int(row['user_count'])
                adjusted_month = (month - target_month) % 12 + 1
                genre_monthly_counts[genre][adjusted_month] = count

    # 결과를 일반 딕셔너리로 정리
    final_results = {
        genre: {month: genre_monthly_counts[genre].get(month, 0) for month in range(1, 13)}
        for genre in genre_list
    }

    final_retention_rates = {}

    for genre, monthly in final_results.items():
        first_month = monthly[1]
        final_retention_rates[genre] = {
            month: round((count / first_month * 100), 2) if first_month > 0 else 0.0
            for month, count in monthly.items()
        }

    try:
        save_FavGenre_csv_to_s3 (
            info_db_no,
            final_retention_rates['Comedy'],
            final_retention_rates['Horror'],
            final_retention_rates['Drama'],
            final_retention_rates['Romance'],
            final_retention_rates['Action'],
            final_retention_rates['Documentary'],
            final_retention_rates['Sci-Fi']
        )
        return jsonify({
            "success": True,
            "message": "CSV 파일이 S3에 저장되었습니다.",
        }), 200
    except Exception as e:
        print(f"CSV 저장 중 오류 발생: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

def analysis_cohort_LastLogin(info_db_no, target_table_user, target_table_sub, target_date):
    info_db = get_info_db_by_info_db_no(info_db_no).to_dict()
    if not info_db:
        return jsonify({"success": False, "message": "DB 정보를 찾을 수 없습니다."}), 404

    user = info_db.get('user')
    host = info_db.get('host')
    password = info_db.get('password')
    port = info_db.get('port')
    name = info_db.get('name')

    engine = create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}")
    metadata = MetaData()

    # 날짜 처리
    # start_date = datetime.strptime(target_date, "%Y-%m-%d")
    start_date = target_date
    target_year = start_date.year
    target_month = start_date.month

    # 1년 후 같은 달의 1일
    try:
        end_date = start_date.replace(year=start_date.year + 1)
    except ValueError:
        end_date = start_date + timedelta(days=365)

    # 테이블 컬럼 매핑
    user_sub_table_columns = get_info_columns_by_info_db_no_origin_table(info_db_no, target_table_sub)
    user_table_columns = get_info_columns_by_info_db_no_origin_table(info_db_no, target_table_user)

    sub_origin_map = {col.analysis_column: col.origin_column for col in user_sub_table_columns}
    user_origin_map = {col.analysis_column: col.origin_column for col in user_table_columns}

    user_sub_table = Table(target_table_sub, metadata, autoload_with=engine)
    user_table = Table(target_table_user, metadata, autoload_with=engine)

    # user_sub_info의 user_id 컬럼 가져오기
    user_id_col_sub = getattr(user_sub_table.c, sub_origin_map['user_id'])
    ended_at_col_sub = getattr(user_sub_table.c, sub_origin_map['ended_at'])

    # user_info의 컬럼
    user_id_col_user = getattr(user_table.c, user_origin_map['user_id'])
    last_login_col_user = getattr(user_table.c, user_origin_map['last_login'])

    last_login_type_list = ['FrequentUser', 'DormantUser', 'ForgottenUser']
    
    # 결과 딕셔너리: {장르: {월: 사용자수}}
    last_login_monthly_counts = {last_login_type: defaultdict(int) for last_login_type in last_login_type_list}

    with engine.connect() as conn:
        first_month_user_query = (
            select(user_id_col_sub)
            .where(
                extract('year', ended_at_col_sub) == target_year,
                extract('month', ended_at_col_sub) == target_month
            )
            .distinct()
        )
        first_month_user_ids = conn.execute(first_month_user_query).scalars().all()

        last_login_user_query = (
            select(
                user_id_col_user,
                func.datediff(func.now(), last_login_col_user).label('last_login_diff')
            )
            .where(user_id_col_user.in_(first_month_user_ids))
        )
        last_login_diff_user_ids = conn.execute(last_login_user_query).mappings().all()

        target_user_ids = {'FrequentUser': [], 'DormantUser': [], 'ForgottenUser': []}
        for row in last_login_diff_user_ids:
            if row['last_login_diff'] <= 7:
                target_user_ids['FrequentUser'].append(row[user_id_col_user.key])
            elif 7 < row['last_login_diff'] <= 30:
                target_user_ids['DormantUser'].append(row[user_id_col_user.key])
            else:
                target_user_ids['ForgottenUser'].append(row[user_id_col_user.key])

        for last_login_type in last_login_type_list:
            monthly_count_query = (
                select(
                    extract('year', ended_at_col_sub).label('year'),
                    extract('month', ended_at_col_sub).label('month'),
                    func.count(func.distinct(user_id_col_sub)).label('user_count')
                )
                .select_from(
                    user_sub_table.join(
                        user_table,
                        user_id_col_sub == user_id_col_user
                    )
                )
                .where(
                    and_(
                        ended_at_col_sub >= start_date,
                        ended_at_col_sub < end_date,
                        user_id_col_sub.in_(target_user_ids[last_login_type]),
                    )
                )
                .group_by(extract('year', ended_at_col_sub), extract('month', ended_at_col_sub))
                .order_by('year', 'month')
            )

            monthly_results = conn.execute(monthly_count_query).mappings().all()

        
            for row in monthly_results:
                year, month, count = int(row['year']), int(row['month']), int(row['user_count'])
                adjusted_month = (month - target_month) % 12 + 1
                last_login_monthly_counts[last_login_type][adjusted_month] = count

            final_results = {
                last_login_type: {month: last_login_monthly_counts[last_login_type].get(month, 0) for month in range(1, 13)}
                for last_login_type in last_login_type_list
            }

    print(f'final_results : {final_results}')
    final_retention_rates = {}

    for last_login_type, monthly in final_results.items():
        first_month = monthly[1]
        final_retention_rates[last_login_type] = {
            month: round((count / first_month * 100), 2) if first_month > 0 else 0.0
            for month, count in monthly.items()
        }

    try:
        save_LastLogin_csv_to_s3 (
            info_db_no,
            final_retention_rates['FrequentUser'],
            final_retention_rates['DormantUser'],
            final_retention_rates['ForgottenUser']
        )
        return jsonify({
            "success": True,
            "message": "CSV 파일이 S3에 저장되었습니다.",
        }), 200
    except Exception as e:
        print(f"CSV 저장 중 오류 발생: {e}")
        return jsonify({"success": False, "error": str(e)}), 500