import os
import json
import requests
import pandas as pd
from pykrx import stock
from datetime import datetime

REST_API_KEY = os.environ["KAKAO_REST_API_KEY"]
CLIENT_SECRET = os.environ["KAKAO_CLIENT_SECRET"]
REFRESH_TOKEN = os.environ["KAKAO_REFRESH_TOKEN"]


def get_access_token():
    res = requests.post("https://kauth.kakao.com/oauth/token", data={
        "grant_type": "refresh_token",
        "client_id": REST_API_KEY,
        "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN,
    })
    res.raise_for_status()
    return res.json()["access_token"]


def get_top_movers():
    today = datetime.now().strftime("%Y%m%d")

    kospi = stock.get_market_ohlcv_by_ticker(today, market="KOSPI")
    kosdaq = stock.get_market_ohlcv_by_ticker(today, market="KOSDAQ")
    df = pd.concat([kospi, kosdaq])
    df = df[df["거래량"] > 0]

    top_rise = df.nlargest(10, "등락률")
    top_fall = df.nsmallest(10, "등락률")
    return top_rise, top_fall


def format_message(top_rise, top_fall):
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [f"[국내 증시 알림] {today}\n"]

    lines.append("📈 급등 Top 10")
    for i, (ticker, row) in enumerate(top_rise.iterrows(), 1):
        name = stock.get_market_ticker_name(ticker)
        lines.append(f"{i}. {name}  {row['등락률']:+.1f}%  {int(row['종가']):,}원")

    lines.append("\n📉 급락 Top 10")
    for i, (ticker, row) in enumerate(top_fall.iterrows(), 1):
        name = stock.get_market_ticker_name(ticker)
        lines.append(f"{i}. {name}  {row['등락률']:+.1f}%  {int(row['종가']):,}원")

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

    message = format_message(top_rise, top_fall)
    print(message)

    print("\n카카오톡 전송 중...")
    result = send_kakao_message(access_token, message)
    print("전송 결과:", result)
