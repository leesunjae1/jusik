import os
import json
import requests
import pandas as pd
import xml.etree.ElementTree as ET
from io import StringIO
from bs4 import BeautifulSoup
from datetime import datetime

REST_API_KEY = os.environ["KAKAO_REST_API_KEY"]
CLIENT_SECRET = os.environ["KAKAO_CLIENT_SECRET"]
REFRESH_TOKEN = os.environ["KAKAO_REFRESH_TOKEN"]

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


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

    # pd.read_html로 정확한 수치 추출
    for df in pd.read_html(StringIO(res.text)):
        if "종목명" in df.columns and "등락률" in df.columns:
            df = df[["종목명", "현재가", "등락률"]].dropna()
            df = df[df["종목명"].str.strip() != "종목명"]
            df["등락률"] = df["등락률"].astype(str).str.replace("%", "").str.replace("+", "").astype(float)
            df["현재가"] = df["현재가"].astype(str).str.replace(",", "").astype(float).astype(int)
            df = df.head(10).reset_index(drop=True)

            # BeautifulSoup으로 종목 코드 추출
            soup = BeautifulSoup(res.text, "lxml")
            table = soup.find("table", class_="type_2")
            codes = []
            if table:
                for tr in table.find_all("tr"):
                    a = tr.find("a", href=lambda h: h and "code=" in h)
                    if a:
                        codes.append(a["href"].split("code=")[-1])

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


def format_message(top_rise, top_fall):
    today = datetime.now().strftime("%Y-%m-%d")

    rise_lines = [f"[국내 증시 알림] {today}\n", "📈 급등 Top 10"]
    for i, row in top_rise.iterrows():
        rise_lines.append(f"{i+1}. {row['종목명']}  {row['등락률']:+.1f}%  {int(row['현재가']):,}원")
        headline = get_news_headline(row["종목명"])
        if headline:
            rise_lines.append(f"   └ {headline}")

    fall_lines = ["📉 급락 Top 10"]
    for i, row in top_fall.iterrows():
        fall_lines.append(f"{i+1}. {row['종목명']}  {row['등락률']:+.1f}%  {int(row['현재가']):,}원")
        headline = get_news_headline(row["종목명"])
        if headline:
            fall_lines.append(f"   └ {headline}")

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
    rise_msg, fall_msg = format_message(top_rise, top_fall)
    print(rise_msg)
    print(fall_msg)

    print("\n카카오톡 전송 중...")
    result1 = send_kakao_message(access_token, rise_msg)
    result2 = send_kakao_message(access_token, fall_msg)
    print("전송 결과:", result1, result2)
