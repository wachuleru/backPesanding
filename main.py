# backend/main.py
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
import secrets
from typing import Dict, Any

app = FastAPI()
print("🚀 BACKEND actualizado y preparado para Render")

# === CORS (permitir frontend externo, ej: GitHub Pages) ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Cambia a tu dominio si lo deseas
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Estructura en memoria ===
rooms: Dict[str, Dict[str, Any]] = {}
FIB = [1, 2, 3, 5, 8, 13, 21, 34]

# === Funciones auxiliares ===
def room_state(room_id: str):
    """Devuelve el estado actual de la sala con votos y título."""
    r = rooms.get(room_id)
    if not r:
        return {"users": {}, "available": FIB, "counts": {}, "title": None, "history": []}

    users = {u: {"vote": info["vote"]} for u, info in r["users"].items()}

    counts: Dict[str, Any] = {}
    pending = 0  # 👈 cantidad de usuarios sin voto

    for info in r["users"].values():
        v = info["vote"]
        if v is None:
            pending += 1
        else:
            counts[v] = counts.get(v, 0) + 1

    # 👇 añadimos la clave especial dentro del mismo dict
    counts["pending"] = pending


    return {
        "users": users,
        "available": FIB,
        "counts": counts,
        "title": r.get("current_title"),
        "history": r.get("history", []),
    }

async def broadcast(room_id: str, message: dict):
    """Envía un mensaje JSON a todos los usuarios conectados a una sala."""
    if room_id not in rooms:
        return
    data = json.dumps(message)
    for user, info in list(rooms[room_id]["users"].items()):
        ws = info["ws"]
        try:
            await ws.send_text(data)
        except Exception as e:
            print(f"Error enviando a {user}: {e}")

# === WebSocket principal ===
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    params = dict(websocket.query_params)
    room = params.get("room")
    user = params.get("user")

    if not room or not user:
        await websocket.accept()
        await websocket.send_text(json.dumps({"type": "error", "msg": "missing room or user"}))
        await websocket.close()
        return

    await websocket.accept()

    # Crear sala si no existe
    if room not in rooms:
        rooms[room] = {
            "users": {},
            "lock": asyncio.Lock(),
            "current_title": None,
            "history": [],
        }

    async with rooms[room]["lock"]:
        if user in rooms[room]["users"]:
            user = f"{user}_{secrets.token_hex(2)}"
        rooms[room]["users"][user] = {"ws": websocket, "vote": None}

    await broadcast(room, {"type": "joined", "user": user, "state": room_state(room)})

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            typ = msg.get("type")

            # === Nuevo: asignar título ===
            if typ == "set_title":
                title = msg.get("title")
                async with rooms[room]["lock"]:
                    rooms[room]["current_title"] = title
                await broadcast(room, {"type": "title_set", "title": title, "state": room_state(room)})

            elif typ == "vote":
                value = msg.get("value")
                async with rooms[room]["lock"]:
                    rooms[room]["users"][user]["vote"] = value
                await broadcast(room, {"type": "vote", "user": user, "value": value, "state": room_state(room)})

            # === Nuevo: reset guarda el resultado previo ===
            elif typ == "reset":
                async with rooms[room]["lock"]:
                    current = rooms[room]
                    # Guardar resultado previo si hay votos
                    votes_snapshot = {
                        "title": current.get("current_title") or "Sin título",
                        "results": room_state(room)["counts"],
                    }
                    current["history"].append(votes_snapshot)

                    # Limpiar votos y título
                    for u in current["users"]:
                        current["users"][u]["vote"] = None
                    current["current_title"] = None

                await broadcast(room, {"type": "reset", "state": room_state(room)})

            elif typ == "request_state":
                await websocket.send_text(json.dumps({"type": "state", "state": room_state(room)}))

    except WebSocketDisconnect:
        async with rooms[room]["lock"]:
            if user in rooms[room]["users"]:
                del rooms[room]["users"][user]
            if not rooms[room]["users"]:
                del rooms[room]
            else:
                await broadcast(room, {"type": "left", "user": user, "state": room_state(room)})

# === Para Render ===
@app.get("/")
async def root():
    return {"status": "Backend running successfully 🚀"}

@app.get("/health")
async def health_check():
    """Verifica si el backend está funcionando correctamente."""
    return {"status": "ok", "message": "Backend operativo 🚀"}

# === Lanzamiento local ===
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
