# app/utils/ws_manager.py
from fastapi import WebSocket
from typing import List

class ConnectionManager:
    def __init__(self):
        # Aquí guardamos a todos los vecinos conectados
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        # Enviar el mensaje a TODOS los conectados
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                # Si falla (se desconectó), lo sacamos de la lista
                self.disconnect(connection)

manager = ConnectionManager()