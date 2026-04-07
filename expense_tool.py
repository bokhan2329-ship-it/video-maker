import uuid
import io
import streamlit as st
import pandas as pd
import plotly.express as px

# --- [UI 디자인 세팅] ---
st.set_page_config(page_title="고정지출 정리기", page_icon="💰", layout="wide")

hide_streamlit_style = """
<style>
#MainMenu {visibility: hidden;}
header {visibility: hidden;}
footer {visibility: hidden;}
</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# --- [상수 정의] ---
CATEGORIES = ["구독서비스", "보험", "월세/관리비", "통신비", "기타"]

CATEGORY_KEYWORDS = {
    "구독서비스": [
        "netflix", "넷플릭스", "youtube", "유튜브", "spotify", "멜론",
        "왓챠", "tving", "웨이브", "wavve", "coupang play", "쿠팡플레이",
        "apple", "구글", "google", "adobe", "microsoft", "ms", "naver",
        "네이버", "카카오", "kakao",
    ],
    "보험": ["보험", "생명", "화재", "손해", "삼성생명", "현대해상", "db손보", "한화생명"],
    "월세/관리비": ["관리비", "월세", "임대", "아파트", "부동산", "전세"],
    "통신비": ["kt", "skt", "lgu+", "lg u+", "통신", "인터넷", "모바일", "핸드폰", "유플러스"],
}

FREQ_MULTIPLIERS = {
    "월간": 1.0,
    "주간": 52.0 / 12.0,
    "연간": 1.0 / 12.0,
}

# 날짜/거래처/금액 후보 컬럼명 목록
DATE_CANDIDATES = ["날짜", "거래일", "거래일자", "date", "일자", "거래날짜"]
MERCHANT_CANDIDATES = ["거래처", "가맹점", "내용", "적요", "상호명", "merchant", "거래내용", "이용가맹점"]
AMOUNT_CANDIDATES = ["출금액", "금액", "이용금액", "출금", "amount", "지출금액", "출금금액"]


# --- [헬퍼 함수] ---
def normalize_monthly(amount: float, freq: str) -> float:
    return amount * FREQ_MULTIPLIERS.get(freq, 1.0)


def assign_category(merchant: str) -> str:
    lower = merchant.lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return cat
    return "기타"


def make_expense_row(name: str, amount: float, freq: str, category: str, source: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "항목명": name,
        "금액": amount,
        "주기": freq,
        "카테고리": category,
        "출처": source,
        "월환산금액": normalize_monthly(amount, freq),
    }


def detect_columns(df: pd.DataFrame) -> dict | None:
    """컬럼명 후보 리스트로 날짜/거래처/금액 컬럼을 자동 매핑."""
    cols_lower = {c.strip().lower(): c for c in df.columns}
    mapping = {}
    for key, candidates in [
        ("date", DATE_CANDIDATES),
        ("merchant", MERCHANT_CANDIDATES),
        ("amount", AMOUNT_CANDIDATES),
    ]:
        found = next((cols_lower[c.lower()] for c in candidates if c.lower() in cols_lower), None)
        if found:
            mapping[key] = found
    if len(mapping) < 3:
        return None
    return mapping


def parse_statement(uploaded_file) -> pd.DataFrame | None:
    """CSV(UTF-8/CP949) 또는 Excel 파일을 파싱해 DataFrame 반환."""
    name = uploaded_file.name.lower()
    try:
        if name.endswith(".xlsx") or name.endswith(".xls"):
            return pd.read_excel(uploaded_file, engine="openpyxl")
        else:
            raw = uploaded_file.read()
            for enc in ("utf-8", "cp949", "euc-kr"):
                try:
                    return pd.read_csv(io.StringIO(raw.decode(enc)))
                except (UnicodeDecodeError, Exception):
                    continue
    except Exception:
        pass
    return None


def detect_recurring(df: pd.DataFrame) -> list[dict]:
    """반복 거래 자동 감지 → 고정지출 후보 리스트 반환."""
    mapping = detect_columns(df)
    if not mapping:
        return []

    work = df[[mapping["date"], mapping["merchant"], mapping["amount"]]].copy()
    work.columns = ["date", "merchant", "amount"]

    # 날짜 파싱
    for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            work["date"] = pd.to_datetime(work["date"], format=fmt)
            break
        except Exception:
            pass
    if not pd.api.types.is_datetime64_any_dtype(work["date"]):
        try:
            work["date"] = pd.to_datetime(work["date"], infer_datetime_format=True)
        except Exception:
            return []

    # 금액 정제 (콤마, 원화 기호 제거)
    work["amount"] = (
        work["amount"]
        .astype(str)
        .str.replace(r"[₩,원\s]", "", regex=True)
        .replace("", "0")
        .astype(float)
    )
    work = work[work["amount"] > 0].dropna()

    candidates = []
    grouped = work.groupby("merchant")

    for merchant, group in grouped:
        if len(group) < 2:
            continue

        sorted_dates = group["date"].sort_values()
        gaps = sorted_dates.diff().dt.days.dropna()
        if len(gaps) == 0:
            continue

        mean_gap = gaps.mean()
        gap_cv = (gaps.std() / mean_gap) if mean_gap > 0 else 999

        # 주기 분류
        if 11 <= mean_gap <= 40:
            freq = "주간"
        elif 41 <= mean_gap <= 100:
            freq = "월간"
        elif 250 <= mean_gap <= 400:
            freq = "연간"
        else:
            continue

        # 규칙성 및 금액 일관성 확인
        if gap_cv >= 0.35:
            continue

        amounts = group["amount"]
        amount_mean = amounts.mean()
        amount_cv = (amounts.std() / amount_mean) if amount_mean > 0 else 999
        if amount_cv >= 0.15:
            continue

        candidates.append(
            make_expense_row(
                name=str(merchant).strip(),
                amount=round(amount_mean),
                freq=freq,
                category=assign_category(str(merchant)),
                source="자동감지",
            )
        )

    return candidates


def existing_keys() -> set:
    return {(e["항목명"].strip().lower(), e["주기"]) for e in st.session_state["expenses"]}


# --- [세션 상태 초기화] ---
if "expenses" not in st.session_state:
    st.session_state["expenses"] = []
if "detected" not in st.session_state:
    st.session_state["detected"] = []

# --- [페이지 헤더] ---
st.markdown("<h1 style='margin-bottom:0'>💰 고정지출 정리기</h1>", unsafe_allow_html=True)
st.caption("은행·카드 명세서를 업로드하거나 직접 입력해 고정지출을 한눈에 정리하세요.")
st.divider()

# ──────────────────────────────────────────────────────────────────────────────
# 섹션 A: 명세서 업로드
# ──────────────────────────────────────────────────────────────────────────────
with st.expander("📂 은행·카드 명세서 업로드", expanded=True):
    uploaded = st.file_uploader(
        "명세서 파일 업로드 (CSV 또는 Excel)",
        type=["csv", "xlsx", "xls"],
        help="날짜, 거래처(가맹점), 출금액 컬럼이 포함된 파일을 올려주세요.",
    )

    if uploaded:
        df = parse_statement(uploaded)
        if df is None:
            st.error("파일을 읽지 못했습니다. CSV 또는 Excel 형식인지 확인해주세요.")
        else:
            mapping = detect_columns(df)
            if mapping:
                st.info(
                    f"인식된 컬럼 — 날짜: **{mapping['date']}** / "
                    f"거래처: **{mapping['merchant']}** / "
                    f"금액: **{mapping['amount']}**"
                )
            else:
                st.warning(
                    "날짜·거래처·금액 컬럼을 자동으로 인식하지 못했습니다. "
                    "아래 직접 입력을 이용해 주세요."
                )

            detected = detect_recurring(df)
            st.session_state["detected"] = detected

            if detected:
                st.success(f"**{len(detected)}개**의 고정지출 후보를 발견했습니다.")
                preview_df = pd.DataFrame(
                    [
                        {
                            "항목명": d["항목명"],
                            "평균금액": f"₩{d['금액']:,.0f}",
                            "주기": d["주기"],
                            "카테고리": d["카테고리"],
                            "월환산금액": f"₩{d['월환산금액']:,.0f}",
                        }
                        for d in detected
                    ]
                )
                st.dataframe(preview_df, use_container_width=True, hide_index=True)

                if st.button("✅ 감지된 고정지출 모두 추가", use_container_width=True):
                    added = 0
                    keys = existing_keys()
                    for item in detected:
                        key = (item["항목명"].strip().lower(), item["주기"])
                        if key not in keys:
                            st.session_state["expenses"].append(item)
                            keys.add(key)
                            added += 1
                    st.success(f"{added}개 항목이 추가되었습니다." if added else "이미 모두 추가된 항목입니다.")
                    st.rerun()
            elif mapping:
                st.info("반복 거래 패턴을 찾지 못했습니다. 직접 입력을 이용해 주세요.")

st.divider()

# ──────────────────────────────────────────────────────────────────────────────
# 섹션 B: 수동 직접 입력
# ──────────────────────────────────────────────────────────────────────────────
with st.expander("✏️ 고정지출 직접 입력", expanded=True):
    with st.form("manual_entry_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            name_input = st.text_input("항목명", placeholder="예: 넷플릭스, 월세")
            amount_input = st.number_input("금액 (원)", min_value=0, step=1000, value=0)
        with col2:
            freq_input = st.selectbox("주기", ["월간", "주간", "연간"])
            category_input = st.selectbox("카테고리", CATEGORIES)
        submitted = st.form_submit_button("➕ 추가", use_container_width=True)

    if submitted:
        if not name_input.strip():
            st.warning("항목명을 입력해주세요.")
        elif amount_input <= 0:
            st.warning("금액을 1원 이상 입력해주세요.")
        else:
            key = (name_input.strip().lower(), freq_input)
            if key in existing_keys():
                st.warning(f"'{name_input}' ({freq_input}) 항목이 이미 존재합니다.")
            else:
                st.session_state["expenses"].append(
                    make_expense_row(name_input.strip(), float(amount_input), freq_input, category_input, "수동입력")
                )
                st.success(f"'{name_input}' 항목이 추가되었습니다!")

st.divider()

# ──────────────────────────────────────────────────────────────────────────────
# 섹션 C: 고정지출 목록
# ──────────────────────────────────────────────────────────────────────────────
expenses = st.session_state["expenses"]

if expenses:
    st.subheader("📋 고정지출 목록")
    header = st.columns([3, 2, 1, 2, 2, 1])
    for col, label in zip(header, ["항목명", "금액", "주기", "카테고리", "월환산금액", ""]):
        col.markdown(f"**{label}**")

    delete_id = None
    for item in expenses:
        cols = st.columns([3, 2, 1, 2, 2, 1])
        cols[0].write(item["항목명"])
        cols[1].write(f"₩{item['금액']:,.0f}")
        cols[2].write(item["주기"])
        cols[3].write(item["카테고리"])
        cols[4].write(f"₩{item['월환산금액']:,.0f}")
        if cols[5].button("🗑️", key=f"del_{item['id']}"):
            delete_id = item["id"]

    if delete_id:
        st.session_state["expenses"] = [e for e in expenses if e["id"] != delete_id]
        st.rerun()

    # 카테고리별 소계
    st.divider()
    cat_df = (
        pd.DataFrame(expenses)
        .groupby("카테고리")["월환산금액"]
        .sum()
        .reset_index()
        .rename(columns={"월환산금액": "월 환산 합계 (원)"})
        .sort_values("월 환산 합계 (원)", ascending=False)
    )
    cat_df["월 환산 합계 (원)"] = cat_df["월 환산 합계 (원)"].apply(lambda x: f"₩{x:,.0f}")
    st.dataframe(cat_df, use_container_width=True, hide_index=True)

    st.divider()

    # ──────────────────────────────────────────────────────────────────────────
    # 섹션 D: 시각화
    # ──────────────────────────────────────────────────────────────────────────
    st.subheader("📊 시각화")

    total_monthly = sum(e["월환산금액"] for e in expenses)
    m1, m2, m3 = st.columns(3)
    m1.metric("💴 월 고정지출 합계", f"₩{total_monthly:,.0f}")
    m2.metric("📅 연간 환산", f"₩{total_monthly * 12:,.0f}")
    m3.metric("📌 항목 수", f"{len(expenses)}개")

    st.markdown("")

    chart_df = pd.DataFrame(expenses)

    col_pie, col_bar = st.columns(2)

    with col_pie:
        pie_data = chart_df.groupby("카테고리")["월환산금액"].sum().reset_index()
        fig_pie = px.pie(
            pie_data,
            values="월환산금액",
            names="카테고리",
            title="카테고리별 월 고정지출 비중",
            color_discrete_sequence=px.colors.qualitative.Pastel,
        )
        fig_pie.update_traces(textposition="inside", textinfo="percent+label")
        st.plotly_chart(fig_pie, use_container_width=True)

    with col_bar:
        bar_data = chart_df.sort_values("월환산금액", ascending=False)
        fig_bar = px.bar(
            bar_data,
            x="항목명",
            y="월환산금액",
            color="카테고리",
            title="항목별 월 환산 금액",
            labels={"월환산금액": "월 환산 금액 (원)", "항목명": "항목명"},
            text_auto=True,
            color_discrete_sequence=px.colors.qualitative.Pastel,
        )
        fig_bar.update_layout(xaxis_tickangle=-30)
        st.plotly_chart(fig_bar, use_container_width=True)

else:
    st.info("아직 등록된 고정지출이 없습니다. 명세서를 업로드하거나 직접 입력해주세요.")
