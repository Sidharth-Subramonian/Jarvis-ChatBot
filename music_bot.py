import os  # <--- ADD THIS
import signal
import subprocess

music_p = None

def play_music(query):
    global music_p
    stop_music()
    print(f"--- Streaming: {query} ---")
    # Adding os.setsid here is what caused the crash without the import
    cmd = f'yt-dlp -f ba -g "ytsearch1:{query}" | xargs mpv --no-video --volume=100'
    music_p = subprocess.Popen(cmd, shell=True, preexec_fn=os.setsid)
    return f"Playing {query} now, sir."

def stop_music():
    global music_p
    # Clean kill
    subprocess.run("pkill -9 mpv", shell=True, stderr=subprocess.DEVNULL)
    music_p = None
    return "Music stopped."