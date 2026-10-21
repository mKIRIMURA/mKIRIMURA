# デイリーダイジェスト

毎朝、次の内容を 1 枚の Markdown にまとめて自動でコミットします。

- ☀️ 今日の天気（既定: 東京）— [Open-Meteo](https://open-meteo.com/)
- 💱 為替レート（米ドル・ユーロ・英ポンド・人民元・韓国ウォン、対円）— [ExchangeRate-API](https://www.exchangerate-api.com/docs/free)
- 🗞️ 政治・経済・技術ニュースの見出し — NHK / Google ニュースの RSS
- 📰 Claude によるニュース要約（`ANTHROPIC_API_KEY` を設定した場合のみ）

最新版は [`latest.md`](latest.md)、過去分は [`reports/`](reports/) にあります。

## 自動実行の設定

`.github/workflows/daily-digest.yml` が毎朝 6:47 (JST) に実行します。Actions タブの **Daily Digest → Run workflow** から手動でも実行できます。

1. （任意）Claude の要約を使う場合: **Settings → Secrets and variables → Actions → Secrets** に `ANTHROPIC_API_KEY` を登録
2. （任意）別の都市にする場合: 同じ画面の **Variables** に `DIGEST_CITY`（例: `大阪`）、`DIGEST_LAT`、`DIGEST_LON` を登録

API キーがなくても、天気・為替・見出し一覧は作成されます。

## ローカルで実行

```bash
pip install -r requirements.txt   # Claude の要約を使う場合のみ必要
python digest.py --stdout          # 画面に表示
python digest.py                   # latest.md と reports/YYYY-MM-DD.md に保存
python -m unittest discover -s tests
```

ニュースの取得元は `digest.py` の `NEWS_FEEDS` に、通貨は `CURRENCIES` に書かれています。
