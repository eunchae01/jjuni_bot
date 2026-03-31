"""테마주 실시간 대시보드 서버"""
import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from kis_api import get_stock_price, get_access_token
from kis_websocket import (
    kis_ws_connect,
    build_theme_snapshot,
    realtime_prices,
    ALL_CODES,
    CODE_TO_NAME,
)

# 각 브라우저 클라이언트마다 큐를 가짐
_client_queues: dict[WebSocket, asyncio.Queue] = {}


def enqueue_all():
    """모든 클라이언트 큐에 최신 스냅샷 넣기"""
    snapshot = build_theme_snapshot()
    if not snapshot:
        return
    message = json.dumps(snapshot, ensure_ascii=False)
    for q in _client_queues.values():
        # 큐가 쌓이면 오래된 것 버리고 최신만 유지
        while not q.empty():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                break
        q.put_nowait(message)


async def periodic_broadcast():
    """1초마다 브라우저에 최신 데이터 푸시"""
    while True:
        await asyncio.sleep(1)
        if _client_queues:
            enqueue_all()


async def on_kis_update():
    """KIS 체결 수신 시 즉시 큐에 넣기"""
    if _client_queues:
        enqueue_all()


async def load_initial_prices():
    """서버 시작 시 REST API로 초기 시세 로드"""
    print("[초기화] REST API로 전 종목 시세 로딩...")
    await get_access_token()
    for code in ALL_CODES:
        try:
            data = await get_stock_price(code)
            if data:
                if not data["name"]:
                    data["name"] = CODE_TO_NAME.get(code, "")
                data["time"] = ""
                realtime_prices[code] = data
            await asyncio.sleep(0.05)
        except Exception as e:
            print(f"  초기 로드 실패 {code}: {e}")
    print(f"[초기화] 완료: {len(realtime_prices)}개 종목")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await load_initial_prices()
    except Exception as e:
        print(f"[초기화] 초기 로드 실패: {e}")
    ws_task = asyncio.create_task(kis_ws_connect(on_kis_update))
    bc_task = asyncio.create_task(periodic_broadcast())
    yield
    ws_task.cancel()
    bc_task.cancel()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    queue: asyncio.Queue = asyncio.Queue()
    _client_queues[ws] = queue

    try:
        # 즉시 현재 스냅샷 전송
        snapshot = build_theme_snapshot()
        if snapshot:
            await ws.send_text(json.dumps(snapshot, ensure_ascii=False))

        # 큐에서 메시지 꺼내서 전송 (receive 대기 안 함)
        while True:
            message = await queue.get()
            await ws.send_text(message)
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        _client_queues.pop(ws, None)


@app.get("/api/themes")
async def get_themes():
    snapshot = build_theme_snapshot()
    if not snapshot or all(len(v["stocks"]) == 0 for v in snapshot.values()):
        return {"message": "데이터 로딩 중..."}
    return snapshot
