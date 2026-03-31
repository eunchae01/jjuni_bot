"""한국투자증권 실시간 WebSocket 체결가 수신"""
import json
import asyncio
import websockets
from kis_api import get_approval_key
from config import THEMES, KIS_WS_URL

# 전체 종목코드 → 테마 역매핑
CODE_TO_THEME: dict[str, str] = {}
CODE_TO_NAME: dict[str, str] = {}
ALL_CODES: list[str] = []

for theme, stocks in THEMES.items():
    for code, name in stocks.items():
        CODE_TO_THEME[code] = theme
        CODE_TO_NAME[code] = name
        if code not in ALL_CODES:
            ALL_CODES.append(code)

# 실시간 데이터 저장소
realtime_prices: dict[str, dict] = {}


def parse_realtime_data(raw: str) -> dict | None:
    """H0STCNT0 실시간 체결 데이터 파싱
    데이터는 | 로 구분, 헤더^데이터 형식
    """
    try:
        # 암호화 여부 확인
        parts = raw.split("|")
        if len(parts) < 4:
            return None

        # parts[0]: 암호화여부, parts[1]: tr_id, parts[2]: 데이터건수, parts[3]: 데이터
        tr_id = parts[1]
        if tr_id != "H0STCNT0":
            return None

        fields = parts[3].split("^")
        if len(fields) < 30:
            return None

        # H0STCNT0 필드 순서 (0-based)
        # 0: 유가증권단축종목코드
        # 1: 주식체결시간 (HHMMSS)
        # 2: 주식현재가
        # 3: 전일대비부호 (1:상한,2:상승,3:보합,4:하한,5:하락)
        # 4: 전일대비
        # 5: 전일대비율
        # 8: 가중평균주식가격
        # 9: 시가
        # 10: 최고가
        # 11: 최저가
        # 12: 매도호가1
        # 13: 매수호가1
        # 14: 체결거래량 (이번 체결 수량)
        # 15: 누적거래량
        # 16: 누적거래대금
        code = fields[0]
        return {
            "code": code,
            "name": CODE_TO_NAME.get(code, ""),
            "price": int(fields[2]),
            "sign": fields[3],
            "change_price": int(fields[4]),
            "change_rate": float(fields[5]),
            "open": int(fields[9]) if fields[9] else 0,
            "high": int(fields[10]) if fields[10] else 0,
            "low": int(fields[11]) if fields[11] else 0,
            "volume": int(fields[15]) if fields[15] else 0,
            "trade_amount": int(fields[16]) if fields[16] else 0,
            "time": fields[1],
        }
    except (IndexError, ValueError) as e:
        print(f"Parse error: {e}")
        return None


def build_theme_snapshot() -> dict:
    """현재 realtime_prices를 테마별로 묶어서 반환"""
    result = {}
    for theme, stocks in THEMES.items():
        theme_stocks = []
        for code in stocks:
            if code in realtime_prices:
                theme_stocks.append(realtime_prices[code])
        theme_stocks.sort(key=lambda x: x["trade_amount"], reverse=True)
        total_amount = sum(s["trade_amount"] for s in theme_stocks)
        result[theme] = {
            "stocks": theme_stocks,
            "total_amount": total_amount,
        }
    return result


async def subscribe(ws, approval_key: str, code: str):
    """종목 실시간 체결가 구독"""
    msg = json.dumps({
        "header": {
            "approval_key": approval_key,
            "custtype": "P",
            "tr_type": "1",
            "content-type": "utf-8",
        },
        "body": {
            "input": {
                "tr_id": "H0STCNT0",
                "tr_key": code,
            }
        }
    })
    await ws.send(msg)


async def kis_ws_connect(on_update):
    """한투 WebSocket에 연결하고 실시간 데이터 수신

    on_update: 데이터 변경 시 호출할 콜백 (async)
    """
    while True:
        try:
            approval_key = await get_approval_key()
            print(f"[KIS WS] Approval key 발급 완료")

            async with websockets.connect(
                KIS_WS_URL,
                ping_interval=30,
                ping_timeout=10,
            ) as ws:
                print(f"[KIS WS] 연결 성공, {len(ALL_CODES)}개 종목 구독 시작")

                # 모든 종목 구독 (한투는 최대 40개 종목 실시간 구독 가능)
                for code in ALL_CODES:
                    await subscribe(ws, approval_key, code)
                    await asyncio.sleep(0.1)

                print(f"[KIS WS] 구독 완료, 실시간 데이터 수신 대기중...")

                async for raw in ws:
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="replace")

                    # PINGPONG 처리
                    if raw.startswith("0") or raw.startswith("1"):
                        parsed = parse_realtime_data(raw)
                        if parsed:
                            realtime_prices[parsed["code"]] = parsed
                            await on_update()

        except (websockets.exceptions.ConnectionClosed, ConnectionError) as e:
            print(f"[KIS WS] 연결 끊김: {e}, 5초 후 재연결...")
        except Exception as e:
            print(f"[KIS WS] 에러: {e}, 5초 후 재연결...")

        await asyncio.sleep(5)
