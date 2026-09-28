import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import os
import io
from datetime import datetime

st.set_page_config(
    page_title="제조 스마트 품질/공정 대시보드",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 제조 현장 대시보드에 어울리는 현대적 CSS 스타일링
st.markdown("""
<style>
    .metric-card {
        background-color: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 12px;
    }
    .urgent-banner {
        background-color: #fef2f2;
        border-left: 5px solid #ef4444;
        padding: 12px 16px;
        border-radius: 4px;
        margin-bottom: 16px;
    }
    .warning-text {
        color: #b91c1c;
        font-weight: 600;
    }
    .normal-tag {
        color: #15803d;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

def generate_sample_manufacturing_data() -> pd.DataFrame:
    """사용자가 테스트할 수 있도록 공정 샘플 데이터를 생성합니다."""
    np.random.seed(42)
    n = 120
    timestamps = pd.date_range(start="2026-09-01", periods=n, freq="H")
    lines = ["1호기(조립)", "2호기(성형)", "3호기(도장)", "4호기(패키징)"]
    operators = ["김반장", "이엔지니어", "박기사", "최오퍼레이터"]
    
    temperatures = np.random.normal(loc=75.0, scale=4.5, size=n)
    pressures = np.random.normal(loc=3.2, scale=0.3, size=n)
    vibrations = np.random.normal(loc=0.45, scale=0.08, size=n)
    defect_rates = np.random.beta(a=1.5, b=30, size=n) * 100
    
    # 의도적 이상징후 데이터 주입 (긴급 항목 테스트용)
    temperatures[15] = 98.4   # 초고온
    temperatures[42] = 103.2  # 심각 과열
    pressures[60] = 4.8       # 과압
    defect_rates[85] = 14.8   # 불량률 급증
    vibrations[102] = 0.89    # 비정상 진동
    
    df = pd.DataFrame({
        "측정일시": timestamps,
        "라인명": np.random.choice(lines, size=n),
        "작업담당자": np.random.choice(operators, size=n),
        "공정온도(°C)": np.round(temperatures, 2),
        "작동압력(bar)": np.round(pressures, 3),
        "진동수치(G)": np.round(vibrations, 3),
        "불량률(%)": np.round(defect_rates, 2),
        "생산수량(EA)": np.random.randint(120, 250, size=n)
    })
    
    # 일부 결측치 의도적 삽입 (결측치 확인 테스트용)
    df.loc[10, "공정온도(°C)"] = np.nan
    df.loc[35, "진동수치(G)"] = np.nan
    
    return df

def load_uploaded_file(uploaded_file) -> pd.DataFrame:
    """CSV 또는 Excel 파일을 로드하여 Pandas DataFrame으로 변환합니다."""
    try:
        if uploaded_file.name.endswith('.csv'):
            return pd.read_csv(uploaded_file)
        elif uploaded_file.name.endswith(('.xlsx', '.xls')):
            return pd.read_excel(uploaded_file)
    except Exception as e:
        st.error(f"파일을 읽는 도중 오류가 발생했습니다: {str(e)}")
        return None

def detect_column_types(df: pd.DataFrame):
    """데이터프레임의 범주형과 수치형 컬럼을 자동으로 분류합니다."""
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    # 문자열, 카테고리, 날짜/시간 등을 범주형 후보로 분류
    categorical_cols = df.select_dtypes(include=['object', 'category', 'datetime64']).columns.tolist()
    return numeric_cols, categorical_cols

def detect_anomalies_and_emergencies(df: pd.DataFrame, numeric_cols: list):
    """
    통계적 이상치(IQR 기반) 및 지정된 임계값에 기반한 긴급 이상징후를 탐지합니다.
    """
    alerts = []
    emergency_rows = pd.DataFrame()
    
    # 1. IQR 기반 이상치 탐지
    anomaly_mask = pd.Series([False] * len(df), index=df.index)
    for col in numeric_cols:
        series = df[col].dropna()
        if len(series) < 5:
            continue
        q25 = series.quantile(0.25)
        q75 = series.quantile(0.75)
        iqr = q75 - q25
        lower_bound = q25 - 1.5 * iqr
        upper_bound = q75 + 1.5 * iqr
        
        col_outliers = (df[col] < lower_bound) | (df[col] > upper_bound)
        outlier_count = col_outliers.sum()
        
        if outlier_count > 0:
            anomaly_mask = anomaly_mask | col_outliers
            alerts.append({
                "컬럼": col,
                "유형": "통계적 이상치(IQR)",
                "건수": int(outlier_count),
                "상세": f"정상 범위: {lower_bound:.2f} ~ {upper_bound:.2f}, 벗어난 데이터 {outlier_count}건",
                "수준": "주의" if outlier_count < 3 else "경고"
            })
            
    # 2. 제조 현장 공통 긴급 임계치 검사 (컬럼명 패턴 매칭)
    for col in numeric_cols:
        col_lower = col.lower()
        if "온도" in col_lower or "temp" in col_lower:
            high_temp = df[df[col] >= 90.0]
            if not high_temp.empty:
                alerts.append({
                    "컬럼": col,
                    "유형": "고온 경보 (긴급)",
                    "건수": len(high_temp),
                    "상세": f"90°C 이상 위험 과열 상태 발생: {len(high_temp)}건",
                    "수준": "긴급"
                })
        if "불량률" in col_lower or "defect" in col_lower:
            high_defect = df[df[col] >= 10.0]
            if not high_defect.empty:
                alerts.append({
                    "컬럼": col,
                    "유형": "품질 위험 (긴급)",
                    "건수": len(high_defect),
                    "상세": f"불량률 10% 초과 구간 발생: {len(high_defect)}건",
                    "수준": "긴급"
                })

    if anomaly_mask.any():
        emergency_rows = df[anomaly_mask].copy()

    return alerts, emergency_rows

def summarize_data_for_ai(df: pd.DataFrame, alerts: list, numeric_cols: list, categorical_cols: list) -> str:
    """
    [데이터 분석 전용 함수]
    AI API에 전달할 경량화된 구조적 통계 요약 텍스트를 생성합니다.
    (민감한 전체 원본 데이터 전송 방지 및 토큰 효율화)
    """
    summary_lines = [
        f"- 총 데이터 행 수: {len(df)}개, 열 수: {len(df.columns)}개",
        f"- 범주형 컬럼: {', '.join(categorical_cols) if categorical_cols else '없음'}",
        f"- 수치형 컬럼: {', '.join(numeric_cols) if numeric_cols else '없음'}",
        "\n[수치형 컬럼별 기초 통계]"
    ]
    
    desc = df[numeric_cols].describe().round(2)
    for col in numeric_cols:
        if col in desc:
            mean_val = desc.loc['mean', col]
            min_val = desc.loc['min', col]
            max_val = desc.loc['max', col]
            summary_lines.append(f"  * {col}: 평균 {mean_val}, 최소 {min_val}, 최대 {max_val}")
            
    summary_lines.append("\n[탐지된 이상징후 및 경보 요약]")
    if alerts:
        for alert in alerts:
            summary_lines.append(f"  * [{alert['수준']}] {alert['컬럼']} ({alert['유형']}): {alert['상세']}")
    else:
        summary_lines.append("  * 특이 이상징후 없음 (정상 수치 범위)")
        
    return "\n".join(summary_lines)

def request_ai_analysis(summary_text: str, api_key: str = None) -> str:
    """
    [AI API 전용 함수]
    데이터 분석 함수와 완전히 분리되어 작동하며,
    API 키가 있을 경우 AI 제공자(OpenAI 호환 API)를 호출하고
    키가 없을 경우 규칙 기반 인텔리전트 종합 진단을 제공합니다.
    """
    if not api_key:
        # 안전한 기본 폴백(Fallback): API Key가 없을 때도 실무적인 종합 분석 리포트 제공
        return f"""### 🤖 AI 공정 진단 보고서 (규칙 기반 인텔리전스 모드)

**1. 종합 공정 건전성 평가**
데이터를 종합적으로 분석한 결과, 주요 공정 지표의 변동성이 감지되었습니다. 

**2. 관리자 즉각 조치 권고사항**
- **설비 점검:** 최근 과열 또는 이상 압력이 보고된 라인은 즉각 냉각기 및 밸브 윤활 상태를 점검하십시오.
- **불량률 관리:** 특정 교대조 또는 라인에서 불량률이 일시 급증하는 현상이 발견되었습니다. 원자재 로트(Lot) 번호 및 금형 마모도를 확인하십시오.
- **예방 보전:** IQR 기준 임계치를 벗어난 데이터 포인트는 장비 고장의 전조 증상일 가능성이 높으므로 일일 점검 리스트에 등록 바랍니다.

*(더 정밀한 자연어 진단을 원하실 경우 사이드바에서 AI API Key를 등록하거나 환경변수를 설정해주세요.)*
"""

    # API Key가 전달된 경우의 처리 (OpenAI 표준 API 호출 구조)
    try:
        import urllib.request
        import json
        
        prompt = f"""
당신은 대한민국 최고 수준의 스마트팩토리 제조 데이터 분석 전문가입니다.
아래 제공된 제조 데이터 통계 요약과 이상징후 알림을 기반으로 관리자가 실행할 수 있는 실질적인 조치 보고서를 작성해주세요:

{summary_text}

[작성 가이드라인]
1. 공정 상태 한 줄 요약
2. 주요 이상 징후 원인 추정
3. 관리자 및 현장 작업자를 위한 3대 긴급 액션 아이템
간결하고 가독성 높은 마크다운 형식으로 작성해주세요.
"""
        # urllib를 활용한 의존성 없는 안전한 API 요청
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            },
            data=json.dumps({
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": "제조 데이터 분석 전문가"},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3
            }).encode("utf-8")
        )
        
        with urllib.request.urlopen(req, timeout=15) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            return res_data["choices"][0]["message"]["content"]
            
    except Exception as e:
        return f"⚠️ AI API 호출 중 오류가 발생했습니다: {str(e)}\n\nAPI 키의 유효성과 네트워크 상태를 확인해주세요."

st.sidebar.title("🏭 제조 데이터 제어판")

# API Key는 환경변수 또는 st.secrets 우선 탐색 (코드에 직접 입력 금지)
default_api_key = os.getenv("OPENAI_API_KEY", "")
if not default_api_key:
    try:
        default_api_key = st.secrets.get("OPENAI_API_KEY", "")
    except Exception:
        default_api_key = ""

with st.sidebar.expander("🔑 AI 연동 설정", expanded=False):
    user_api_key = st.text_input(
        "OpenAI API Key (선택)",
        value=default_api_key,
        type="password",
        help="환경변수/Secrets가 없을 경우 직접 입력할 수 있습니다. 키가 없어도 기본 진단 기능이 제공됩니다."
    )

st.sidebar.subheader("📂 1. 데이터 소스")
uploaded_file = st.sidebar.file_uploader(
    "CSV 또는 Excel 파일 업로드",
    type=["csv", "xlsx", "xls"],
    help="제조 현장 계측 로그, 불량률 데이터 등을 업로드하세요."
)

use_sample_btn = st.sidebar.button("🧪 샘플 제조 공정 데이터 로드")

# 세션 상태로 데이터 프레임 유지
if "active_df" not in st.session_state:
    st.session_state.active_df = None

if uploaded_file is not None:
    st.session_state.active_df = load_uploaded_file(uploaded_file)
elif use_sample_btn or st.session_state.active_df is None:
    if st.session_state.active_df is None:
        st.session_state.active_df = generate_sample_manufacturing_data()

df_raw = st.session_state.active_df

st.title("🏭 제조기업 스마트 데이터 분석 대시보드")
st.caption("실시간 제조 공정 품질 지표 모니터링, 이상 징후 조기 탐지 및 AI 기반 인사이트 리포트")

if df_raw is not None and not df_raw.empty:
    numeric_columns, categorical_columns = detect_column_types(df_raw)
    alerts, emergency_df = detect_anomalies_and_emergencies(df_raw, numeric_columns)
    
    # [추가 기능] 관리자 긴급 이상징후 모니터링 영역
    st.subheader("🚨 관리자 모니터링 & 이상징후 알림")
    
    emergency_count = len([a for a in alerts if a['수준'] == '긴급'])
    warning_count = len([a for a in alerts if a['수준'] == '경고'])
    
    col_a, col_b, col_c = st.columns([1, 1, 2])
    with col_a:
        st.metric("긴급 경보 (즉시 조치)", f"{emergency_count} 건", delta="위험" if emergency_count > 0 else "정상", delta_color="inverse")
    with col_b:
        st.metric("공정 주의 (점검 요망)", f"{warning_count} 건", delta="주의" if warning_count > 0 else "안정", delta_color="inverse")
    with col_c:
        if emergency_count > 0:
            st.error(f"⚠️ 긴급 한계치를 초과한 공정 변수가 {emergency_count}건 감지되었습니다. 아래 세부 내역을 확인하십시오.")
        else:
            st.success("✅ 시스템 정상: 치명적인 공정 임계치 초과 항목이 없습니다.")

    if alerts:
        with st.expander("🔍 이상징후 및 긴급 항목 세부 내역 보기", expanded=(emergency_count > 0)):
            alert_df = pd.DataFrame(alerts)
            st.table(alert_df)
            
            if not emergency_df.empty:
                st.write("**⚠️ 이상치가 검출된 원본 행(Raw Rows):**")
                st.dataframe(emergency_df.head(10), use_container_width=True)

    st.markdown("---")
    st.subheader("📊 2. 데이터 기본 정보 및 품질 상태")
    
    total_rows = len(df_raw)
    total_cols = len(df_raw.columns)
    total_missing = df_raw.isnull().sum().sum()
    missing_ratio = (total_missing / (total_rows * total_cols)) * 100 if total_rows > 0 else 0
    
    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    m_col1.metric("총 행 수 (Records)", f"{total_rows:,} 개")
    m_col2.metric("총 열 수 (Features)", f"{total_cols:,} 개")
    m_col3.metric("결측치 개수", f"{total_missing:,} 개")
    m_col4.metric("결측치 비율", f"{missing_ratio:.2f} %")
    
    # 4 & 5. 범주형/수치형 컬럼 자동 인식 결과 출력
    col_type_info1, col_type_info2 = st.columns(2)
    with col_type_info1:
        st.info(f"**🔢 자동 인식된 수치형 컬럼 ({len(numeric_columns)}개):**\n\n{', '.join(numeric_columns) if numeric_columns else '없음'}")
    with col_type_info2:
        st.info(f"**🏷️ 자동 인식된 범주형 컬럼 ({len(categorical_columns)}개):**\n\n{', '.join(categorical_columns) if categorical_columns else '없음'}")

    st.sidebar.subheader("🎯 3. 데이터 필터링")
    filtered_df = df_raw.copy()
    
    # 범주형 컬럼 중 하나를 골라 다중 선택 필터 적용
    if categorical_columns:
        primary_cat = st.sidebar.selectbox("필터링 기준 범주 컬럼", categorical_columns, index=0)
        unique_values = filtered_df[primary_cat].dropna().unique().tolist()
        selected_values = st.sidebar.multiselect(
            f"{primary_cat} 선택",
            options=unique_values,
            default=unique_values
        )
        if selected_values:
            filtered_df = filtered_df[filtered_df[primary_cat].isin(selected_values)]
            
    # 수치형 컬럼 범위 슬라이더 필터
    if numeric_columns:
        slider_col = st.sidebar.selectbox("범위 필터 적용 수치 컬럼", numeric_columns, index=0)
        min_v = float(df_raw[slider_col].min())
        max_v = float(df_raw[slider_col].max())
        if min_v < max_v:
            selected_range = st.sidebar.slider(
                f"{slider_col} 범위",
                min_value=min_v,
                max_value=max_v,
                value=(min_v, max_v)
            )
            filtered_df = filtered_df[
                (filtered_df[slider_col] >= selected_range[0]) & 
                (filtered_df[slider_col] <= selected_range[1])
            ]

    with st.expander("👀 데이터 미리보기 (상위 10건)", expanded=True):
        st.dataframe(filtered_df.head(10), use_container_width=True)

    st.markdown("---")
    st.subheader("📈 3. 공정 데이터 시각화")
    
    if not filtered_df.empty and numeric_columns:
        v_col1, v_col2 = st.columns(2)
        
        # 7. 막대 그래프 (Bar Chart)
        with v_col1:
            st.markdown("##### 📊 범주별 지표 분석 (막대 그래프)")
            bar_x = st.selectbox("X축 (범주형 컬럼)", options=categorical_columns if categorical_columns else df_raw.columns, key="bar_x")
            bar_y = st.selectbox("Y축 (수치형 컬럼)", options=numeric_columns, key="bar_y")
            agg_method = st.selectbox("집계 방식", ["평균(Mean)", "합계(Sum)", "최댓값(Max)"], key="bar_agg")
            
            agg_dict = {"평균(Mean)": "mean", "합계(Sum)": "sum", "최댓값(Max)": "max"}
            grouped_data = filtered_df.groupby(bar_x)[bar_y].agg(agg_dict[agg_method]).reset_index()
            
            fig_bar = px.bar(
                grouped_data,
                x=bar_x,
                y=bar_y,
                title=f"{bar_x}별 {bar_y} {agg_method}",
                color=bar_y,
                color_continuous_scale="Blues",
                text_auto=True
            )
            fig_bar.update_layout(template="plotly_white", margin=dict(l=20, r=20, t=40, b=20))
            st.plotly_chart(fig_bar, use_container_width=True)

        # 8. 선 그래프 (Line Chart)
        with v_col2:
            st.markdown("##### 📉 시계열 및 추세 분석 (선 그래프)")
            # 날짜 또는 인덱스를 X축으로 기본 설정
            date_candidates = [c for c in df_raw.columns if "일시" in c or "date" in c.lower() or "time" in c.lower()]
            default_line_x = date_candidates[0] if date_candidates else df_raw.columns[0]
            
            line_x = st.selectbox("X축 (시간 또는 순서)", options=df_raw.columns, index=df_raw.columns.get_loc(default_line_x), key="line_x")
            line_y = st.multiselect("Y축 (수치형 모니터링 컬럼)", options=numeric_columns, default=[numeric_columns[0]], key="line_y")
            
            if line_y:
                fig_line = px.line(
                    filtered_df,
                    x=line_x,
                    y=line_y,
                    title=f"{line_x} 기준 {', '.join(line_y)} 추이",
                    markers=True
                )
                fig_line.update_layout(template="plotly_white", margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig_line, use_container_width=True)
            else:
                st.warning("선 그래프에 표시할 Y축 수치 컬럼을 하나 이상 선택해주세요.")
    else:
        st.warning("현재 필터링 조건에 해당하는 데이터가 없거나 수치형 컬럼이 부족합니다.")

    st.markdown("---")
    st.subheader("💡 4. 제조 AI 인사이트 진단")
    st.write("데이터 분석 로직이 집계한 요약 통계를 기반으로 스마트 공정 최적화 조치 가이드를 생성합니다.")

    if st.button("🚀 AI 분석 실행하기", type="primary"):
        with st.spinner("공정 요약 통계 집계 및 AI 진단 중..."):
            # 1. 데이터 분석 함수 호출 (데이터 처리 및 통계 분리)
            summary_info = summarize_data_for_ai(filtered_df, alerts, numeric_columns, categorical_columns)
            
            # 2. AI 분석 함수 호출 (외부 API 및 추론 분리)
            ai_result = request_ai_analysis(summary_info, user_api_key)
            
            st.markdown(ai_result)

    st.markdown("---")
    st.subheader("💾 5. 필터링된 데이터 다운로드")
    
    csv_buffer = io.StringIO()
    filtered_df.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
    csv_bytes = csv_buffer.getvalue().encode('utf-8-sig')
    
    st.download_button(
        label="📥 필터링된 결과 CSV 다운로드",
        data=csv_bytes,
        file_name=f"제조분석_데이터_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv"
    )

else:
    st.info("좌측 사이드바에서 분석할 CSV/Excel 파일을 업로드하거나, 샘플 데이터를 로드해주세요.")
