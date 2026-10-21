import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import digest  # noqa: E402

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item><title>AI\xe6\x96\xb0\xe3\x83\xa2\xe3\x83\x87\xe3\x83\xab\xe7\x99\xba\xe8\xa1\xa8 - Example News</title>
<link>https://example.com/a</link><source url="https://example.com">Example News</source>
<pubDate>Wed, 21 Oct 2026 01:00:00 GMT</pubDate></item>
<item><title>\xe5\x8f\xa4\xe3\x81\x84\xe8\xa8\x98\xe4\xba\x8b</title><link>https://example.com/old</link>
<pubDate>Mon, 12 Oct 2026 01:00:00 GMT</pubDate></item>
</channel></rss>"""


class DigestTest(unittest.TestCase):
    def test_parse_weather(self):
        w = digest.parse_weather({"daily": {
            "weather_code": [61], "temperature_2m_max": [21.4], "temperature_2m_min": [14.0],
            "precipitation_probability_max": [80], "wind_speed_10m_max": [12.3]}})
        self.assertEqual(w["weather"], "小雨")
        self.assertEqual(w["rain"], 80)

    def test_parse_fx_inverts_rates(self):
        fx = digest.parse_fx({"rates": {"USD": 0.0066667, "EUR": 0.0062, "KRW": 9.2}})
        self.assertAlmostEqual(fx["USD"], 150.0, places=1)
        self.assertNotIn("GBP", fx)

    def test_parse_rss_strips_source_suffix(self):
        items = digest.parse_rss(RSS, "Google ニュース")
        self.assertEqual(items[0].title, "AI新モデル発表")
        self.assertEqual(items[0].source, "Example News")
        self.assertEqual(items[1].source, "Google ニュース")

    def test_get_news_filters_old_and_duplicates(self):
        original = digest.fetch
        digest.fetch = lambda url, timeout=20.0: RSS
        try:
            now = dt.datetime(2026, 10, 21, 7, 0, tzinfo=digest.JST)
            news = digest.get_news({"技術": ["https://a", "https://b"]}, now)
        finally:
            digest.fetch = original
        self.assertEqual([h.title for h in news["技術"]], ["AI新モデル発表"])

    def test_render_without_data(self):
        now = dt.datetime(2026, 10, 21, 7, 0, tzinfo=digest.JST)
        out = digest.render(now, "東京", None, None, {"政治": []}, None)
        self.assertIn("2026年10月21日", out)
        self.assertIn("取得できませんでした", out)
        self.assertNotIn("ニュースのまとめ", out)


if __name__ == "__main__":
    unittest.main()
