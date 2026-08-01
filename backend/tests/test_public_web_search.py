from app.search.public_web import parse_bing_rss


def test_parse_bing_rss_returns_bounded_unique_http_sources():
    payload = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0"><channel>
      <item><title>官方 &amp; 更新</title><link>https://example.com/update</link><description>最新 &lt;b&gt;公告&lt;/b&gt;</description></item>
      <item><title>重复</title><link>https://example.com/update</link><description>重复项</description></item>
      <item><title>无效</title><link>file:///secret</link><description>无效地址</description></item>
      <item><title>第二条</title><link>https://example.org/report</link><description>报告摘要</description></item>
    </channel></rss>"""

    sources = parse_bing_rss(payload, limit=2)

    assert [source.url for source in sources] == [
        "https://example.com/update",
        "https://example.org/report",
    ]
    assert sources[0].title == "官方 & 更新"
    assert sources[0].snippet == "最新 公告"
    assert sources[0].provider == "bing-rss"
