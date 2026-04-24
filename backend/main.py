from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import uuid
import psutil
import socket
import time
import asyncio
import os
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlmodel import SQLModel, Field, Session, select, create_engine
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
import pygame
import threading
import sys

# Add jarvis to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), 'jarvis'))
from jarvis.brain import run_jarvis
from jarvis import config as jarvis_config

# Global State
start_time = time.time()
stopwatch_state = {
    "isRunning": False,
    "elapsedMilliseconds": 0,
    "lastStartTimestamp": None
}
current_media_state = {
    "status": "stopped",
    "currentTrack": None,
    "volume": 0.5
}


# Database Setup
sqlite_file_name = "piconsole.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url, echo=False)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

# Models
class Timer(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    label: str
    durationSeconds: int
    endTime: float
    isActive: bool = True

class Alarm(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    label: str
    timeFormatted: str # e.g., "07:30"
    isActive: bool = True

# Audio Engine
class SoundManager:
    def __init__(self):
        try:
            pygame.mixer.init()
            self.enabled = True
        except Exception as e:
            print(f"Audio init failed: {e}")
            self.enabled = False

    def play_alarm(self):
        if not self.enabled: return
        # In a real app, you'd have an actual mp3 file.
        # For now, we'll try to play a system beep or a placeholder
        print("BEEP BEEP! Timer Finished!")

sound_manager = SoundManager()
scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(title="PiConsole Backend", lifespan=lifespan)

# Jarvis Control State
jarvis_thread = None

class JarvisCommand(BaseModel):
    command: str


# Models
class TimerRequest(BaseModel):
    label: str
    durationSeconds: int

class TimerResponse(BaseModel):
    id: str
    label: str
    remainingSeconds: int

class AlarmRequest(BaseModel):
    label: str
    timeFormatted: str

class AlarmResponse(BaseModel):
    id: str
    label: str
    timeFormatted: str
    isActive: bool

class StopwatchAction(BaseModel):
    action: str

class StopwatchResponse(BaseModel):
    isRunning: bool
    elapsedMilliseconds: int

class MediaRequest(BaseModel):
    action: str
    volume: Optional[float] = None

class MediaResponse(BaseModel):
    status: str
    currentTrack: Optional[str] = None
    volume: Optional[float] = None

class StatusResponse(BaseModel):
    deviceName: str
    ipAddress: str
    uptime: str
    cpuUsage: float
    ramUsage: float
    temperature: float
    isOnline: bool

# Connection Manager for WebSockets
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()

# Background task for live stats
async def broadcast_stats():
    while True:
        status = await get_status()
        await manager.broadcast({"type": "status", "data": status.dict()})
        await asyncio.sleep(1)

@app.on_event("startup")
async def start_broadcasting():
    asyncio.create_task(broadcast_stats())

# WebSocket Endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text() # Keep alive
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Endpoints
@app.get("/status", response_model=StatusResponse)
async def get_status():
    uptime_seconds = int(time.time() - start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m"
    
    # Get IP Address
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_addr = s.getsockname()[0]
        s.close()
    except Exception:
        ip_addr = "127.0.0.1"

    # CPU/RAM
    cpu_percent = psutil.cpu_percent(interval=None)
    ram = psutil.virtual_memory()

    # Temperature (Mocked for cross-platform compatibility, real would use vcgencmd or similar)
    try:
        temp = psutil.sensors_temperatures()
        temperature = 42.0 # default mock
        if 'cpu_thermal' in temp:
            temperature = temp['cpu_thermal'][0].current
        elif 'coretemp' in temp:
            temperature = temp['coretemp'][0].current
    except Exception:
        temperature = 45.0

    return StatusResponse(
        deviceName=socket.gethostname(),
        ipAddress=ip_addr,
        uptime=uptime_str,
        cpuUsage=cpu_percent,
        ramUsage=ram.percent,
        temperature=temperature,
        isOnline=True
    )

@app.post("/timer", response_model=TimerResponse)
async def create_timer(request: TimerRequest):
    end_time = time.time() + request.durationSeconds
    timer = Timer(label=request.label, durationSeconds=request.durationSeconds, endTime=end_time)
    
    with Session(engine) as session:
        session.add(timer)
        session.commit()
        session.refresh(timer)
    
    # Schedule the alarm
    scheduler.add_job(
        sound_manager.play_alarm, 
        'date', 
        run_date=time.fromtimestamp(end_time),
        id=timer.id
    )
    
    return TimerResponse(id=timer.id, label=timer.label, remainingSeconds=request.durationSeconds)

@app.delete("/timer/{id}")
async def delete_timer(id: str):
    with Session(engine) as session:
        timer = session.get(Timer, id)
        if timer:
            session.delete(timer)
            session.commit()
            if scheduler.get_job(id):
                scheduler.remove_job(id)
    return {"message": "Timer deleted"}

@app.post("/alarm", response_model=AlarmResponse)
async def create_alarm(request: AlarmRequest):
    alarm = Alarm(label=request.label, timeFormatted=request.timeFormatted)
    
    with Session(engine) as session:
        session.add(alarm)
        session.commit()
        session.refresh(alarm)
    
    # Simple alarm scheduling (logic for daily repeat would go here)
    # For now, just store it
    return AlarmResponse(id=alarm.id, label=alarm.label, timeFormatted=alarm.timeFormatted, isActive=alarm.isActive)

@app.delete("/alarm/{id}")
async def delete_alarm(id: str):
    with Session(engine) as session:
        alarm = session.get(Alarm, id)
        if alarm:
            session.delete(alarm)
            session.commit()
    return {"message": "Alarm deleted"}

def calculate_elapsed():
    global stopwatch_state
    if stopwatch_state["isRunning"]:
        now_ms = int(time.time() * 1000)
        start_ms = stopwatch_state["lastStartTimestamp"]
        return stopwatch_state["elapsedMilliseconds"] + (now_ms - start_ms)
    return stopwatch_state["elapsedMilliseconds"]

@app.get("/stopwatch", response_model=StopwatchResponse)
async def get_stopwatch():
    return StopwatchResponse(
        isRunning=stopwatch_state["isRunning"],
        elapsedMilliseconds=calculate_elapsed()
    )

@app.post("/stopwatch", response_model=StopwatchResponse)
async def control_stopwatch(request: StopwatchAction):
    global stopwatch_state
    now_ms = int(time.time() * 1000)
    
    if request.action == "start" and not stopwatch_state["isRunning"]:
        stopwatch_state["isRunning"] = True
        stopwatch_state["lastStartTimestamp"] = now_ms
    elif request.action == "stop" and stopwatch_state["isRunning"]:
        stopwatch_state["isRunning"] = False
        stopwatch_state["elapsedMilliseconds"] += (now_ms - stopwatch_state["lastStartTimestamp"])
    elif request.action == "reset":
        stopwatch_state["isRunning"] = False
        stopwatch_state["elapsedMilliseconds"] = 0
        stopwatch_state["lastStartTimestamp"] = None

    return StopwatchResponse(
        isRunning=stopwatch_state["isRunning"],
        elapsedMilliseconds=calculate_elapsed()
    )

@app.post("/media", response_model=MediaResponse)
async def control_media(request: MediaRequest):
    global current_media_state
    
    if request.action == "play":
        current_media_state["status"] = "playing"
        if not current_media_state["currentTrack"]:
            current_media_state["currentTrack"] = "Lo-Fi Beats"
    elif request.action == "pause":
        current_media_state["status"] = "paused"
    elif request.action in ("next", "prev"):
        current_media_state["status"] = "playing"
        current_media_state["currentTrack"] = f"Track {int(time.time()) % 100}"
    elif request.action == "volume":
        if request.volume is not None:
            current_media_state["volume"] = request.volume

    return MediaResponse(**current_media_state)

@app.post("/find-phone")
async def find_phone():
    # In a pro version, this sends an FCM message.
    # For now, we simulate the logic.
    print("Sending 'Ring' command to phone...")
    return {"success": True, "message": "Phone is ringing"}

@app.post("/reboot")
async def reboot():
    os.system("sudo reboot")
    return {"message": "Rebooting..."}

@app.post("/shutdown")
async def shutdown():
    os.system("sudo shutdown -h now")
    return {"message": "Shutting down..."}

@app.post("/mute")
async def mute():
    # Toggle mute using amixer
    os.system("amixer set Master toggle")
    return {"message": "Audio toggled"}

# Jarvis Endpoints
@app.get("/jarvis/status")
async def get_jarvis_status():
    return {
        "isRunning": jarvis_thread is not None and jarvis_thread.is_alive(),
        "enabled": jarvis_config.JARVIS_ENABLED
    }

@app.post("/jarvis/toggle")
async def toggle_jarvis():
    global jarvis_thread
    
    if jarvis_thread is not None and jarvis_thread.is_alive():
        # Stop Jarvis
        jarvis_config.JARVIS_ENABLED = False
        return {"message": "Stopping Jarvis... (may take a moment to finish current listening cycle)"}
    else:
        # Start Jarvis
        jarvis_config.JARVIS_ENABLED = True
        jarvis_thread = threading.Thread(target=run_jarvis, daemon=True)
        jarvis_thread.start()
        return {"message": "Jarvis started"}

@app.post("/jarvis/command")
async def jarvis_command(request: JarvisCommand):
    # This could be used to send text commands to the brain directly
    # For now, we'll just log it as the brain is designed for voice loop
    print(f"Received text command for Jarvis: {request.command}")
    return {"message": "Text command received", "command": request.command}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
