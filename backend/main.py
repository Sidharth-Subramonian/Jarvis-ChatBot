from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List
import json
import shutil
from pathlib import Path
import uuid
import psutil
import socket
import time
from datetime import datetime
import asyncio
import os
import socket
from contextlib import asynccontextmanager
from zeroconf import ServiceInfo, Zeroconf
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlmodel import SQLModel, Field, Session, select, create_engine
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
import pygame
import threading
import sys
import firebase_admin
from firebase_admin import credentials, messaging

# Initialize Firebase Admin
try:
    cred = credentials.Certificate(os.path.join(os.path.dirname(__file__), "firebase-adminsdk.json"))
    firebase_admin.initialize_app(cred)
except Exception as e:
    print(f"Failed to initialize Firebase Admin SDK: {e}")

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
fcm_token = None


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
    ringtone: str = "default"

class Alarm(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    label: str
    timeFormatted: str # e.g., "07:30 PM"
    isActive: bool = True
    ringtone: str = "default"
    repeatDays: Optional[str] = None  # JSON list like '["Mon","Tue"]' or null for one-shot

# Ringtone directory
RINGTONE_DIR = Path(os.path.dirname(__file__)) / "ringtones"
RINGTONE_DIR.mkdir(exist_ok=True)

# Audio Engine
class SoundManager:
    def __init__(self):
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=1)
            self.enabled = True
            self._generate_default_tones()
        except Exception as e:
            print(f"Audio init failed: {e}")
            self.enabled = False

    def _generate_default_tones(self):
        """Generate built-in default ringtone files if they don't exist."""
        try:
            import numpy as np
            sample_rate = 22050
            defaults = {
                "classic_beep.wav": [(880, 0.3)] * 6,
                "gentle_chime.wav": [(523, 0.4), (659, 0.4), (784, 0.5)],
                "urgent_alarm.wav": [(1000, 0.15), (800, 0.15)] * 8,
            }
            for fname, pattern in defaults.items():
                fpath = RINGTONE_DIR / fname
                if not fpath.exists():
                    chunks = []
                    for freq, dur in pattern:
                        t = np.linspace(0, dur, int(sample_rate * dur), False)
                        wave = (np.sin(2 * np.pi * freq * t) * 32767 * 0.7).astype(np.int16)
                        silence = np.zeros(int(sample_rate * 0.2), dtype=np.int16)
                        chunks.extend([wave, silence])
                    full = np.concatenate(chunks)
                    snd = pygame.sndarray.make_sound(full)
                    import wave as wavmod
                    with wavmod.open(str(fpath), 'w') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(sample_rate)
                        wf.writeframes(full.tobytes())
                    print(f"Generated default ringtone: {fname}")
        except Exception as e:
            print(f"Failed to generate default tones: {e}")

    def play_ringtone(self, ringtone: str = "default"):
        if not self.enabled:
            print("🔔 Alarm fired! (audio disabled)")
            return
        
        try:
            if ringtone == "default":
                ringtone = "classic_beep.wav"
            
            fpath = RINGTONE_DIR / ringtone
            if fpath.exists():
                print(f"🔔 Playing ringtone: {ringtone}")
                pygame.mixer.music.load(str(fpath))
                pygame.mixer.music.play()
                # Wait for it to finish (max 30s)
                clock = pygame.time.Clock()
                while pygame.mixer.music.get_busy():
                    clock.tick(10)
            else:
                print(f"🔔 Ringtone '{ringtone}' not found, playing fallback beep")
                # Fallback: generate quick beep
                import numpy as np
                t = np.linspace(0, 0.3, int(22050 * 0.3), False)
                wave = (np.sin(2 * np.pi * 880 * t) * 32767 * 0.8).astype(np.int16)
                snd = pygame.sndarray.make_sound(wave)
                for _ in range(6):
                    snd.play()
                    pygame.time.wait(500)
        except Exception as e:
            print(f"Error playing ringtone: {e}")

    def stop(self):
        """Stop any currently playing alarm."""
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass

sound_manager = SoundManager()
scheduler = AsyncIOScheduler()

# Zeroconf Registration
zeroconf = Zeroconf()
service_info = None

def register_zeroconf():
    global service_info
    ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    desc = {'model': 'Raspberry Pi 4', 'name': socket.gethostname()}
    service_info = ServiceInfo(
        "_piconsole._tcp.local.",
        f"{socket.gethostname()}._piconsole._tcp.local.",
        addresses=[socket.inet_aton(ip)],
        port=8000,
        properties=desc,
        server=f"{socket.gethostname()}.local."
    )
    zeroconf.register_service(service_info)
    print(f"Zeroconf service registered at {ip}:8000")

def unregister_zeroconf():
    global service_info
    if service_info:
        zeroconf.unregister_service(service_info)
        zeroconf.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    scheduler.start()
    register_zeroconf()
    yield
    scheduler.shutdown()
    unregister_zeroconf()

app = FastAPI(title="PiConsole Backend", lifespan=lifespan)

# Jarvis Control State
jarvis_thread = None

class JarvisCommand(BaseModel):
    command: str


# Models
class TimerRequest(BaseModel):
    label: str
    durationSeconds: int
    ringtone: str = "default"

class TimerResponse(BaseModel):
    id: str
    label: str
    remainingSeconds: int
    ringtone: str = "default"

class AlarmRequest(BaseModel):
    label: str
    timeFormatted: str
    ringtone: str = "default"
    repeatDays: Optional[List[str]] = None  # e.g. ["Mon", "Wed", "Fri"]

class AlarmResponse(BaseModel):
    id: str
    label: str
    timeFormatted: str
    isActive: bool
    ringtone: str = "default"
    repeatDays: Optional[List[str]] = None

class StopwatchAction(BaseModel):
    action: str

class StopwatchResponse(BaseModel):
    isRunning: bool
    elapsedMilliseconds: int

class MediaRequest(BaseModel):
    action: str
    volume: Optional[float] = None
    query: Optional[str] = None

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

class DeviceRegistrationRequest(BaseModel):
    token: str
    deviceName: str

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
    timer = Timer(label=request.label, durationSeconds=request.durationSeconds, endTime=end_time, ringtone=request.ringtone)
    
    with Session(engine) as session:
        session.add(timer)
        session.commit()
        session.refresh(timer)
    
    # Schedule the alarm with ringtone
    def on_timer_fire(timer_id, label, ringtone):
        sound_manager.play_ringtone(ringtone)
        # Broadcast timer fired event
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(manager.broadcast({"type": "timer_fired", "data": {"id": timer_id, "label": label}}))
        except Exception:
            pass

    scheduler.add_job(
        on_timer_fire,
        'date', 
        run_date=datetime.fromtimestamp(end_time),
        args=[timer.id, timer.label, request.ringtone],
        id=timer.id
    )
    
    # Broadcast timer created event for live sync
    await manager.broadcast({
        "type": "timer_created",
        "data": {"id": timer.id, "label": timer.label, "remainingSeconds": request.durationSeconds, "ringtone": request.ringtone}
    })
    
    return TimerResponse(id=timer.id, label=timer.label, remainingSeconds=request.durationSeconds, ringtone=request.ringtone)

@app.delete("/timer/{id}")
async def delete_timer(id: str):
    with Session(engine) as session:
        timer = session.get(Timer, id)
        if timer:
            session.delete(timer)
            session.commit()
            if scheduler.get_job(id):
                scheduler.remove_job(id)
    await manager.broadcast({"type": "timer_deleted", "data": {"id": id}})
    return {"message": "Timer deleted"}

@app.post("/alarm", response_model=AlarmResponse)
async def create_alarm(request: AlarmRequest):
    repeat_json = json.dumps(request.repeatDays) if request.repeatDays else None
    alarm = Alarm(label=request.label, timeFormatted=request.timeFormatted, ringtone=request.ringtone, repeatDays=repeat_json)
    
    with Session(engine) as session:
        session.add(alarm)
        session.commit()
        session.refresh(alarm)
    
    # Schedule the alarm
    _schedule_alarm(alarm.id, request.timeFormatted, request.ringtone, request.repeatDays, alarm.label)
    
    # Broadcast alarm created event
    await manager.broadcast({
        "type": "alarm_created",
        "data": {"id": alarm.id, "label": alarm.label, "timeFormatted": alarm.timeFormatted, 
                 "isActive": True, "ringtone": request.ringtone, "repeatDays": request.repeatDays}
    })
    
    return AlarmResponse(id=alarm.id, label=alarm.label, timeFormatted=alarm.timeFormatted, 
                         isActive=alarm.isActive, ringtone=request.ringtone, repeatDays=request.repeatDays)

@app.delete("/alarm/{id}")
async def delete_alarm(id: str):
    with Session(engine) as session:
        alarm = session.get(Alarm, id)
        if alarm:
            session.delete(alarm)
            session.commit()
    try:
        scheduler.remove_job(f"alarm_{id}")
    except Exception:
        pass
    await manager.broadcast({"type": "alarm_deleted", "data": {"id": id}})
    return {"message": "Alarm deleted"}

def _schedule_alarm(alarm_id, time_formatted, ringtone, repeat_days, label):
    """Schedule an alarm job. Supports one-shot and recurring."""
    try:
        from datetime import datetime as dt, timedelta
        import pytz
        tz = pytz.timezone("Asia/Kolkata")
        now = dt.now(tz)
        
        alarm_time = dt.strptime(time_formatted, "%I:%M %p")
        alarm_dt = now.replace(hour=alarm_time.hour, minute=alarm_time.minute, second=0, microsecond=0)
        
        if alarm_dt <= now:
            alarm_dt += timedelta(days=1)

        def on_alarm_fire(a_id, a_label, a_ringtone, a_repeat_days):
            sound_manager.play_ringtone(a_ringtone)
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                loop.create_task(manager.broadcast({"type": "alarm_fired", "data": {"id": a_id, "label": a_label}}))
            except Exception:
                pass
            # Re-schedule if recurring
            if a_repeat_days:
                _schedule_alarm(a_id, time_formatted, a_ringtone, a_repeat_days, a_label)

        if repeat_days:
            # For recurring, check if tomorrow's day is in the repeat list
            day_map = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
            target_days = [day_map[d] for d in repeat_days if d in day_map]
            # Find next matching day
            for offset in range(1, 8):
                candidate = now + timedelta(days=offset)
                if candidate.weekday() in target_days:
                    alarm_dt = candidate.replace(hour=alarm_time.hour, minute=alarm_time.minute, second=0, microsecond=0)
                    break
            # Also check today
            today_alarm = now.replace(hour=alarm_time.hour, minute=alarm_time.minute, second=0, microsecond=0)
            if today_alarm > now and now.weekday() in target_days:
                alarm_dt = today_alarm

        # Remove old job if exists
        try:
            scheduler.remove_job(f"alarm_{alarm_id}")
        except Exception:
            pass

        scheduler.add_job(
            on_alarm_fire,
            'date',
            run_date=alarm_dt,
            args=[alarm_id, label, ringtone, repeat_days],
            id=f"alarm_{alarm_id}"
        )
        print(f"🔔 Alarm '{label}' scheduled for {alarm_dt.strftime('%I:%M %p on %A')}")
    except Exception as e:
        print(f"Failed to schedule alarm: {e}")

# Snooze endpoint
@app.post("/snooze/{alarm_id}")
async def snooze_alarm(alarm_id: str, minutes: int = 5):
    """Snooze an alarm by rescheduling it N minutes from now."""
    sound_manager.stop()
    snooze_time = datetime.now() + __import__('datetime').timedelta(minutes=minutes)
    
    # Find the alarm's ringtone
    ringtone = "default"
    with Session(engine) as session:
        alarm = session.get(Alarm, alarm_id)
        if alarm:
            ringtone = alarm.ringtone
    
    def on_snooze_fire():
        sound_manager.play_ringtone(ringtone)
    
    scheduler.add_job(on_snooze_fire, 'date', run_date=snooze_time, id=f"snooze_{alarm_id}")
    print(f"😴 Alarm snoozed for {minutes} minutes")
    return {"message": f"Snoozed for {minutes} minutes"}

# Ringtone management endpoints
@app.get("/ringtones")
async def list_ringtones():
    """List all available ringtone files."""
    ringtones = []
    for f in RINGTONE_DIR.iterdir():
        if f.suffix.lower() in [".wav", ".mp3", ".ogg"]:
            ringtones.append({"name": f.name, "size": f.stat().st_size})
    return {"ringtones": ringtones}

@app.post("/ringtones/upload")
async def upload_ringtone(file: UploadFile = File(...)):
    """Upload a custom ringtone file."""
    allowed = [".wav", ".mp3", ".ogg"]
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"File type {ext} not supported. Use: {allowed}")
    
    dest = RINGTONE_DIR / file.filename
    with open(dest, "wb") as buf:
        shutil.copyfileobj(file.file, buf)
    
    print(f"📁 Ringtone uploaded: {file.filename}")
    return {"message": "Ringtone uploaded", "name": file.filename}

@app.delete("/ringtones/{filename}")
async def delete_ringtone(filename: str):
    """Delete a custom ringtone."""
    fpath = RINGTONE_DIR / filename
    if fpath.exists():
        fpath.unlink()
        return {"message": f"Ringtone '{filename}' deleted"}
    raise HTTPException(status_code=404, detail="Ringtone not found")

# Stop alarm endpoint
@app.post("/alarm/stop")
async def stop_alarm():
    """Stop any currently playing alarm sound."""
    sound_manager.stop()
    return {"message": "Alarm stopped"}

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
    from jarvis.music_bot import play_music, stop_music, toggle_pause, set_volume, get_current_state
    
    if request.action == "play":
        if request.query:
            play_music(request.query)
        else:
            toggle_pause()
    elif request.action == "pause":
        toggle_pause()
    elif request.action == "stop":
        stop_music()
    elif request.action in ("next", "prev"):
        # Just play something random or a default lo-fi for now
        play_music("lo-fi beats")
    elif request.action == "volume":
        if request.volume is not None:
            set_volume(int(request.volume * 100))

    state = get_current_state()
    # Broadcast media update
    await manager.broadcast({"type": "media_update", "data": state})
    
    return MediaResponse(**state)

@app.post("/find-phone")
async def find_phone():
    global fcm_token
    if not fcm_token:
        print("No device registered to ring.")
        return {"success": False, "message": "No device registered"}
    
    try:
        message = messaging.Message(
            data={"action": "find_phone"},
            token=fcm_token,
        )
        response = messaging.send(message)
        print(f"Successfully sent FCM message: {response}")
        return {"success": True, "message": "Phone is ringing via FCM"}
    except Exception as e:
        print(f"Error sending FCM message: {e}")
        return {"success": False, "message": str(e)}

@app.post("/register-device")
async def register_device(request: DeviceRegistrationRequest):
    global fcm_token
    fcm_token = request.token
    print(f"Registered FCM token for {request.deviceName}: {fcm_token}")
    return {"message": "Device registered successfully", "success": True}

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
