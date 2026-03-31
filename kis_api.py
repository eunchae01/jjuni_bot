"""한국투자증권 API 연동 모듈"""
import time
import httpx
from config import KIS_APP_KEY, KIS_APP_SECRET, KIS_BASE_URL

_token_cache = {"token": None, "expires": 0}


async def get_access_token() -> str:
    """OAuth 토큰 발급 (캐싱, 실패 시 재시도)"""
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires"]:
        return _token_cache["token"]

    for attempt in range(3):
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{KIS_BASE_URL}/oauth2/tokenP",
                json={
                    "grant_type": "client_credentials",
                    "appkey": KIS_APP_KEY,
                    "appsecret": KIS_APP_SECRET,
                },
            )
            data = resp.json()
            if "access_token" in data:
                _token_cache["token"] = data["access_token"]
                _token_cache["expires"] = now + int(data.get("expires_in", 86400)) - 60
                return _token_cache["token"]

            print(f"[토큰] 발급 실패 (시도 {attempt+1}): {data.get('error_description', data)}")
            if attempt < 2:
                import asyncio
                await asyncio.sleep(62)  # 1분 제한 대기

    raise RuntimeError("토큰 발급 실패")


async def get_stock_price(stock_code: str) -> dict:
    """종목 현재가/등락률/거래대금 조회"""
    token = await get_access_token()
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
        "tr_id": "FHKST01010100",
    }
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price",
            headers=headers,
            params=params,
        )
        data = resp.json()

    if data.get("rt_cd") != "0":
        return None

    out = data.get("output", {})
    return {
        "code": stock_code,
        "name": out.get("hts_kor_isnm", ""),
        "price": int(out.get("stck_prpr", 0)),
        "change_rate": float(out.get("prdy_ctrt", 0)),
        "change_price": int(out.get("prdy_vrss", 0)),
        "volume": int(out.get("acml_vol", 0)),
        "trade_amount": int(out.get("acml_tr_pbmn", 0)),  # 누적 거래대금
        "high": int(out.get("stck_hgpr", 0)),
        "low": int(out.get("stck_lwpr", 0)),
        "open": int(out.get("stck_oprc", 0)),
        "sign": out.get("prdy_vrss_sign", "3"),  # 1상한 2상승 3보합 4하한 5하락
    }


async def get_approval_key() -> str:
    """웹소켓 접속키 발급"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{KIS_BASE_URL}/oauth2/Approval",
            json={
                "grant_type": "client_credentials",
                "appkey": KIS_APP_KEY,
                "secretkey": KIS_APP_SECRET,
            },
        )
        return resp.json().get("approval_key")
