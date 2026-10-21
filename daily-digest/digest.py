"""毎日のダイジェスト(天気・為替・政治/経済/技術ニュース)を生成する。

使い方:
    python digest.py                 # reports/YYYY-MM-DD.md と latest.md を書き出す
    python digest.py --stdout        # ファイルを書かずに標準出力へ

環境変数(すべて任意):
    DIGEST_CITY        表示する都市名 (既定: 東京)
    DIGEST_LAT/LON     緯度・経度 (既定: 東京駅)
    ANTHROPIC_API_KEY  設定するとニュースを Claude が要約する。未設定なら見出し一覧のみ。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path

JST = dt.timezone(dt.timedelta(hours=9))
USER_AGENT = "daily-digest/1.0 (+https://github.com/mKIRIMURA/mKIRIMURA)"
HEADLINES_PER_CATEGORY = 8

NEWS_FEEDS: dict[str, list[str]] = {
    "政治": [
        "https://www3.nhk.or.jp/rss/news/cat4.xml",
        "https://news.google.com/rss/search?q=%E6%94%BF%E6%B2%BB+when:1d&hl=ja&gl=JP&ceid=JP:ja",
    ],
    "経済": [
        "https://www3.nhk.or.jp/rss/news/cat5.xml",
        "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=ja&gl=JP&ceid=JP:ja",
    ],
    "技術": [
        "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=ja&gl=JP&ceid=JP:ja",
        "https://www3.nhk.or.jp/rss/news/cat3.xml",
    ],
}

CURRENCIES = [("USD", "米ドル"), ("EUR", "ユーロ"), ("GBP", "英ポンド"), ("CNY", "人民元"), ("KRW", "韓国ウォン")]

# WMO weather code -> 日本語
WEATHER_CODES = {
    0: "快晴", 1: "晴れ", 2: "一部曇り", 3: "曇り", 45: "霧", 48: "霧(着氷)",
    51: "弱い霧雨", 53: "霧雨", 55: "強い霧雨", 56: "着氷性の霧雨", 57: "強い着氷性の霧雨",
    61: "小雨", 63: "雨", 65: "大雨", 66: "着氷性の雨", 67: "強い着氷性の雨",
    71: "小雪", 73: "雪", 75: "大雪", 77: "霧雪",
    80: "にわか雨", 81: "強いにわか雨", 82: "激しいにわか雨", 85: "にわか雪", 86: "強いにわか雪",
    95: "雷雨", 96: "雷雨(ひょう)", 99: "激しい雷雨(ひょう)",
}


@dataclass
class Headline:
    title: str
    link: str
    source: str
    published: dt.datetime | None


def fetch(url: str, timeout: float = 20.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ---------------------------------------------------------------- 天気

def get_weather(lat: float, lon: float) -> dict:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}&timezone=Asia%2FTokyo&forecast_days=1"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
        "precipitation_probability_max,wind_speed_10m_max"
    )
    return parse_weather(json.loads(fetch(url)))


def parse_weather(data: dict) -> dict:
    d = data["daily"]
    return {
        "weather": WEATHER_CODES.get(d["weather_code"][0], f"コード{d['weather_code'][0]}"),
        "max": d["temperature_2m_max"][0],
        "min": d["temperature_2m_min"][0],
        "rain": d["precipitation_probability_max"][0],
        "wind": d["wind_speed_10m_max"][0],
    }


# ---------------------------------------------------------------- 為替

def get_fx() -> dict:
    return parse_fx(json.loads(fetch("https://open.er-api.com/v6/latest/JPY")))


def parse_fx(data: dict) -> dict:
    """JPY 基準のレートを「1 外貨 = N 円」に変換する。"""
    rates = data["rates"]
    out = {code: 1 / rates[code] for code, _ in CURRENCIES if rates.get(code)}
    out["_updated"] = data.get("time_last_update_utc", "")
    return out


# ---------------------------------------------------------------- ニュース

def parse_rss(xml_bytes: bytes, default_source: str) -> list[Headline]:
    root = ET.fromstring(xml_bytes)
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        source = (item.findtext("source") or default_source).strip()
        # Google News は「見出し - 媒体名」形式なので媒体名を外す
        suffix = f" - {source}"
        if title.endswith(suffix):
            title = title[: -len(suffix)]
        published = None
        if pub := item.findtext("pubDate"):
            try:
                published = parsedate_to_datetime(pub)
            except (TypeError, ValueError):
                pass
        items.append(Headline(title, (item.findtext("link") or "").strip(), source, published))
    return items


def get_news(feeds: dict[str, list[str]], now: dt.datetime) -> dict[str, list[Headline]]:
    since = now - dt.timedelta(hours=36)
    result = {}
    for category, urls in feeds.items():
        seen, headlines = set(), []
        for url in urls:
            source = "NHK" if "nhk.or.jp" in url else "Google ニュース"
            try:
                items = parse_rss(fetch(url), source)
            except Exception as e:  # 1 つのフィードの失敗で全体を止めない
                print(f"warn: {category} {url}: {e}", file=sys.stderr)
                continue
            for h in items:
                if h.published and h.published.tzinfo and h.published < since:
                    continue
                if h.title in seen:
                    continue
                seen.add(h.title)
                headlines.append(h)
        result[category] = headlines[:HEADLINES_PER_CATEGORY]
    return result


# ---------------------------------------------------------------- Claude 要約

def summarize_with_claude(news: dict[str, list[Headline]]) -> str | None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    import anthropic

    listing = "\n".join(
        f"[{cat}] {h.title} ({h.source})" for cat, hs in news.items() for h in hs
    )
    prompt = (
        "以下は今日のニュース見出しです。政治・経済・技術の各カテゴリについて、"
        "主要な動きを日本語で 2〜4 個の箇条書きにまとめてください。"
        "見出しに書かれていない事実は補わないでください。"
        "出力は Markdown で、各カテゴリを「### 政治」のような見出しで始め、前置きは不要です。\n\n"
        + listing
    )
    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model="claude-opus-5-5",
            max_tokens=4000,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as e:
        print(f"warn: Claude 要約に失敗: {e}", file=sys.stderr)
        return None
    if response.stop_reason == "refusal":
        return None
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return text or None


# ---------------------------------------------------------------- 出力

def render(now: dt.datetime, city: str, weather: dict | None, fx: dict | None,
           news: dict[str, list[Headline]], summary: str | None) -> str:
    lines = [f"# デイリーダイジェスト {now:%Y年%m月%d日}", "", f"_生成: {now:%Y-%m-%d %H:%M} JST_", ""]

    lines += [f"## ☀️ 今日の天気({city})", ""]
    if weather:
        lines += [
            f"- 天気: **{weather['weather']}**",
            f"- 気温: 最高 {weather['max']:.1f}℃ / 最低 {weather['min']:.1f}℃",
            f"- 降水確率: {weather['rain']}%",
            f"- 最大風速: {weather['wind']:.1f} km/h",
        ]
    else:
        lines.append("- 取得できませんでした")
    lines.append("")

    lines += ["## 💱 為替(対円)", ""]
    if fx:
        lines += ["| 通貨 | レート |", "|---|---|"]
        for code, name in CURRENCIES:
            if code in fx:
                rate = fx[code]
                lines.append(f"| {name} ({code}) | {rate:,.2f} 円 |" if rate >= 1 else f"| {name} ({code}) | {rate:.4f} 円 |")
        if fx.get("_updated"):
            lines += ["", f"_レート更新: {fx['_updated']}_"]
    else:
        lines.append("- 取得できませんでした")
    lines.append("")

    if summary:
        lines += ["## 📰 ニュースのまとめ", "", summary, ""]

    lines += ["## 🗞️ 見出し", ""]
    for category, headlines in news.items():
        lines += [f"### {category}", ""]
        if not headlines:
            lines.append("- 取得できませんでした")
        for h in headlines:
            lines.append(f"- [{h.title}]({h.link}) — {h.source}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stdout", action="store_true", help="ファイルに書かず標準出力へ")
    parser.add_argument("--out-dir", default=str(Path(__file__).parent))
    args = parser.parse_args()

    now = dt.datetime.now(JST)
    city = os.environ.get("DIGEST_CITY", "東京")
    lat = float(os.environ.get("DIGEST_LAT", "35.681"))
    lon = float(os.environ.get("DIGEST_LON", "139.767"))

    weather = fx = None
    try:
        weather = get_weather(lat, lon)
    except Exception as e:
        print(f"warn: 天気の取得に失敗: {e}", file=sys.stderr)
    try:
        fx = get_fx()
    except Exception as e:
        print(f"warn: 為替の取得に失敗: {e}", file=sys.stderr)
    news = get_news(NEWS_FEEDS, now)
    summary = summarize_with_claude(news)

    report = render(now, city, weather, fx, news, summary)
    if args.stdout:
        print(report)
        return
    out_dir = Path(args.out_dir)
    (out_dir / "reports").mkdir(parents=True, exist_ok=True)
    (out_dir / "reports" / f"{now:%Y-%m-%d}.md").write_text(report, encoding="utf-8")
    (out_dir / "latest.md").write_text(report, encoding="utf-8")
    print(f"wrote {out_dir / 'latest.md'}")


if __name__ == "__main__":
    main()
