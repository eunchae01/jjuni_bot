"""테마별 뉴스 헤드라인 수집 (Google News RSS)"""
import asyncio
import re
import time
import httpx

# 테마명 → 뉴스 검색 키워드
THEME_KEYWORDS = {
    "해운 관련주": "해운주",
    "방산/전쟁": "방산주",
    "석유 전쟁": "석유 관련주",
    "태양광 에너지": "태양광 관련주",
    "풍력 관련주": "풍력 에너지 주식",
    "ESS 관련주": "ESS 에너지저장 주식",
    "수소 관련주": "수소 관련주",
    "2차전지 소재/부품": "2차전지 관련주",
}

_news_cache: dict[str, list[str]] = {}
_cache_time: float = 0


def _clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&quot;", '"').replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&apos;", "'").replace("&#39;", "'")
    return text.strip()


async def fetch_theme_news(theme: str, keyword: str) -> list[str]:
    """Google News RSS에서 테마 관련 최신 뉴스 최대 5건"""
    try:
        url = "https://news.google.com/rss/search"
        params = {
            "q": keyword,
            "hl": "ko",
            "gl": "KR",
            "ceid": "KR:ko",
        }
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url, params=params)

        titles = re.findall(r"<title>(.+?)</title>", resp.text)
        results = []
        for title in titles[2:]:
            cleaned = _clean_html(title)
            cleaned = re.sub(r"\s*-\s*[^\-]+$", "", cleaned)
            if cleaned:
                results.append(cleaned)
                if len(results) >= 5:
                    break

        return results
    except Exception as e:
        print(f"[뉴스] {theme} 조회 실패: {e}")
        return ""


async def get_all_theme_news() -> dict[str, list[str]]:
    """모든 테마의 최신 뉴스 (5분 캐싱)"""
    global _news_cache, _cache_time

    now = time.time()
    if _news_cache and now - _cache_time < 300:
        return _news_cache

    tasks = []
    themes = []
    for theme, keyword in THEME_KEYWORDS.items():
        themes.append(theme)
        tasks.append(fetch_theme_news(theme, keyword))

    results = await asyncio.gather(*tasks)
    _news_cache = {theme: headlines for theme, headlines in zip(themes, results)}
    _cache_time = now

    fetched = sum(1 for v in _news_cache.values() if v)
    print(f"[뉴스] {fetched}/{len(_news_cache)}개 테마 뉴스 수집 완료")
    return _news_cache
