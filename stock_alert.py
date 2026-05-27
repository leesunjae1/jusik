import os
import json
import requests
import pandas as pd
import xml.etree.ElementTree as ET
from io import StringIO
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

REST_API_KEY = os.environ["KAKAO_REST_API_KEY"]
CLIENT_SECRET = os.environ["KAKAO_CLIENT_SECRET"]
REFRESH_TOKEN = os.environ["KAKAO_REFRESH_TOKEN"]
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DB_ID = os.environ["NOTION_DB_ID"]

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}


def get_access_token():
    res = requests.post("https://kauth.kakao.com/oauth/token", data={
        "grant_type": "refresh_token",
        "client_id": REST_API_KEY,
        "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN,
    })
    res.raise_for_status()
    return res.json()["access_token"]


def fetch_rank(sosok, page_type):
    url = f"https://finance.naver.com/sise/{page_type}.naver?sosok={sosok}"
    res = requests.get(url, headers=HEADERS)
    res.encoding = "euc-kr"

    for df in pd.read_html(StringIO(res.text)):
        if "종목명" in df.columns and "등락률" in df.columns:
            df = df[["종목명", "현재가", "등락률"]].dropna()
            df = df[df["종목명"].str.strip() != "종목명"]
            df["등락률"] = df["등락률"].astype(str).str.replace("%", "").str.replace("+", "").astype(float)
            df["현재가"] = df["현재가"].astype(str).str.replace(",", "").astype(float).astype(int)
            df = df.head(10).reset_index(drop=True)
            return df

    return pd.DataFrame()


def get_top_movers():
    top_rise = pd.concat([
        fetch_rank("0", "sise_rise"),
        fetch_rank("1", "sise_rise"),
    ]).nlargest(10, "등락률").reset_index(drop=True)

    top_fall = pd.concat([
        fetch_rank("0", "sise_fall"),
        fetch_rank("1", "sise_fall"),
    ]).nsmallest(10, "등락률").reset_index(drop=True)

    return top_rise, top_fall


def get_news_headline(name):
    try:
        query = requests.utils.quote(f"{name} 주가")
        url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
        res = requests.get(url, headers=HEADERS, timeout=5)
        root = ET.fromstring(res.content)
        for item in root.findall(".//item/title")[:1]:
            title = (item.text or "").rsplit(" - ", 1)[0].strip()
            if title:
                return title[:40] + "..." if len(title) > 40 else title
    except Exception:
        pass
    return ""


def get_yesterday_names(category):
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    # 주말 처리: 월요일이면 금요일 데이터 조회
    weekday = datetime.now().weekday()
    if weekday == 0:  # 월요일
        yesterday = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")

    res = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
        headers=NOTION_HEADERS,
        json={
            "filter": {
                "and": [
                    {"property": "날짜", "date": {"equals": yesterday}},
                    {"property": "구분", "select": {"equals": category}},
                ]
            }
        },
    )
    if res.status_code != 200:
        return set()

    names = set()
    for page in res.json().get("results", []):
        props = page.get("properties", {})
        title_prop = props.get("종목명", {}).get("title", [])
        if title_prop:
            names.add(title_prop[0]["plain_text"])
    return names


def save_to_notion(df, category, yesterday_names):
    today = datetime.now().strftime("%Y-%m-%d")
    for i, row in df.iterrows():
        name = row["종목명"]
        is_consecutive = name in yesterday_names
        headline = row.get("뉴스", "")

        page = {
            "parent": {"database_id": NOTION_DB_ID},
            "properties": {
                "종목명": {"title": [{"text": {"content": name}}]},
                "날짜": {"date": {"start": today}},
                "구분": {"select": {"name": category}},
                "순위": {"number": i + 1},
                "등락률": {"number": float(row["등락률"])},
                "현재가": {"number": int(row["현재가"])},
                "뉴스": {"rich_text": [{"text": {"content": headline}}]},
                "연속여부": {"checkbox": is_consecutive},
            },
        }
        res = requests.post("https://api.notion.com/v1/pages", headers=NOTION_HEADERS, json=page)
        if res.status_code not in (200, 201):
            print(f"Notion 저장 실패 ({name}): {res.status_code} {res.text[:200]}")


def format_message(top_rise, top_fall, rise_consecutive, fall_consecutive):
    today = datetime.now().strftime("%Y-%m-%d")

    rise_lines = [f"[국내 증시 알림] {today}\n", "📈 급등 Top 10"]
    for i, row in top_rise.iterrows():
        marker = "🔁" if row["종목명"] in rise_consecutive else ""
        rise_lines.append(f"{i+1}. {marker}{row['종목명']}  {row['등락률']:+.1f}%  {int(row['현재가']):,}원")
        if row.get("뉴스"):
            rise_lines.append(f"   └ {row['뉴스']}")

    fall_lines = ["📉 급락 Top 10"]
    for i, row in top_fall.iterrows():
        marker = "🔁" if row["종목명"] in fall_consecutive else ""
        fall_lines.append(f"{i+1}. {marker}{row['종목명']}  {row['등락률']:+.1f}%  {int(row['현재가']):,}원")
        if row.get("뉴스"):
            fall_lines.append(f"   └ {row['뉴스']}")

    if rise_consecutive or fall_consecutive:
        fall_lines.append("\n🔁 = 전일에 이어 연속 등장")

    return "\n".join(rise_lines), "\n".join(fall_lines)


def send_kakao_message(access_token, text):
    res = requests.post(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        headers={"Authorization": f"Bearer {access_token}"},
        data={"template_object": json.dumps({
            "object_type": "text",
            "text": text,
            "link": {"web_url": "https://finance.naver.com/sise/"},
        })},
    )
    res.raise_for_status()
    return res.json()


if __name__ == "__main__":
    print("액세스 토큰 발급 중...")
    access_token = get_access_token()

    print("증시 데이터 수집 중...")
    top_rise, top_fall = get_top_movers()

    print("뉴스 헤드라인 수집 중...")
    for df in [top_rise, top_fall]:
        df["뉴스"] = df["종목명"].apply(get_news_headline)

    print("노션 연속 종목 조회 중...")
    rise_consecutive = get_yesterday_names("급등")
    fall_consecutive = get_yesterday_names("급락")

    print(f"연속 급등: {rise_consecutive}")
    print(f"연속 급락: {fall_consecutive}")

    print("노션 저장 중...")
    save_to_notion(top_rise, "급등", rise_consecutive)
    save_to_notion(top_fall, "급락", fall_consecutive)

    print("카카오톡 메시지 작성 중...")
    rise_msg, fall_msg = format_message(top_rise, top_fall, rise_consecutive, fall_consecutive)
    print(rise_msg)
    print(fall_msg)

    print("\n카카오톡 전송 중...")
    result1 = send_kakao_message(access_token, rise_msg)
    result2 = send_kakao_message(access_token, fall_msg)
    print("전송 결과:", result1, result2)
