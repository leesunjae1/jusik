import os
import json
import requests
import pandas as pd
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
    soup = BeautifulSoup(res.text, "lxml")

    rows = []
    table = soup.find("table", class_="type_2")
    if not table:
        return pd.DataFrame()

    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 6:
            continue
        name_tag = tds[1].find("a")
        if not name_tag:
            continue
        name = name_tag.get_text(strip=True)
        href = name_tag.get("href", "")
        code = href.split("code=")[-1] if "code=" in href else ""
        try:
            price = int(tds[2].get_text(strip=True).replace(",", ""))
            rate = float(tds[5].get_text(strip=True).replace("%", "").replace("+", ""))
        except (ValueError, IndexError):
            continue
        if name and code:
            rows.append({"종목명": name, "코드": code, "현재가": price, "등락률": rate})

    return pd.DataFrame(rows).head(10)


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


def get_news_headline(code):
    try:
        url = f"https://finance.naver.com/item/news_news.naver?code={code}"
        res = requests.get(url, headers=HEADERS, timeout=5)
        res.encoding = "euc-kr"
        soup = BeautifulSoup(res.text, "lxml")
        table = soup.find("table", class_="type5")
        if table:
            title_td = table.find("td", class_="title")
            if title_td:
                title = title_td.get_text(strip=True)
                return title[:40] + "..." if len(title) > 40 else title
    except Exception:
        pass
    return ""


def format_message(top_rise, top_fall):
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [f"[국내 증시 알림] {today}\n"]

    lines.append("📈 급등 Top 10")
    for i, row in top_rise.iterrows():
        lines.append(f"{i+1}. {row['종목명']}  {row['등락률']:+.1f}%  {int(row['현재가']):,}원")
        headline = get_news_headline(row["코드"])
        if headline:
            lines.append(f"   └ {headline}")

    lines.append("\n📉 급락 Top 10")
    for i, row in top_fall.iterrows():
        lines.append(f"{i+1}. {row['종목명']}  {row['등락률']:+.1f}%  {int(row['현재가']):,}원")
        headline = get_news_headline(row["코드"])
        if headline:
            lines.append(f"   └ {headline}")

    return "\n".join(lines)


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
    message = format_message(top_rise, top_fall)
    print(message)

    print("\n카카오톡 전송 중...")
    result = send_kakao_message(access_token, message)
    print("전송 결과:", result)
