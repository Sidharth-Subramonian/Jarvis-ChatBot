import os
import subprocess
import signal
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class MusicPlayer:
    """Manages YouTube music streaming with graceful process management."""
    
    def __init__(self):
        """Initialize music player with no active process."""
        self.process: Optional[subprocess.Popen] = None
        self.current_query: Optional[str] = None
    
    def play(self, query: str) -> str:
        """
        Search YouTube and play music.
        
        Args:
            query: Song name or artist to search for
            
        Returns:
            Status message
        """
        self.stop()  # Stop any existing playback
        
        if not query or not query.strip():
            logger.warning("Empty query provided to play()")
            return "No song specified, sir."
        
        self.current_query = query
        logger.info(f"Starting playback: {query}")
        
        cmd = (
            f'yt-dlp --format ba -g "ytsearch1:{query}" | '
            f'xargs mpv --no-video --volume=100 '
            f'--ao=alsa --audio-device=alsa/hw:2,0 '
            f'--input-ipc-server=/tmp/mpvsocket'
        )
        
        try:
            # Create process group to allow killing entire tree
            self.process = subprocess.Popen(
                cmd,
                shell=True,
                preexec_fn=os.setsid,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            logger.info(f"Music process started (PID: {self.process.pid})")
            return f"Playing {query} now, sir."
        except Exception as e:
            logger.error(f"Failed to start music playback: {e}")
            return f"Failed to play music: {str(e)}"
    
    def stop(self) -> str:
        """
        Stop current music playback gracefully.
        
        Returns:
            Status message
        """
        try:
            if self.process and self.process.poll() is None:
                # Gracefully terminate process group
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                self.process.wait(timeout=2)
                logger.info("Music stopped gracefully")
            else:
                # Fallback: hard kill if graceful termination fails
                subprocess.run("pkill -9 mpv", shell=True, stderr=subprocess.DEVNULL)
                logger.info("Music stopped (hard kill)")
        except subprocess.TimeoutExpired:
            # Force kill if graceful termination times out
            subprocess.run("pkill -9 mpv", shell=True, stderr=subprocess.DEVNULL)
            logger.warning("Music forced to stop (timeout during graceful termination)")
        except Exception as e:
            logger.error(f"Error stopping music: {e}")
        finally:
            # Clean up socket file
            try:
                if os.path.exists("/tmp/mpvsocket"):
                    os.remove("/tmp/mpvsocket")
            except Exception as e:
                logger.warning(f"Failed to clean up socket: {e}")
            
            self.process = None
            self.current_query = None
        
        return "Music stopped."
    
    def is_playing(self) -> bool:
        """
        Check if music is currently playing.
        
        Returns:
            True if music process is active, False otherwise
        """
        return self.process is not None and self.process.poll() is None
    
    def cleanup(self) -> None:
        """Ensure clean shutdown of music player."""
        self.stop()


# Global player instance
_player = MusicPlayer()


def play_music(query: str) -> str:
    """
    Public interface to play music.
    
    Args:
        query: Song name or artist to search for
        
    Returns:
        Status message
    """
    return _player.play(query)


def stop_music() -> str:
    """
    Public interface to stop music.
    
    Returns:
        Status message
    """
    return _player.stop()


def is_playing() -> bool:
    """
    Public interface to check if music is playing.
    
    Returns:
        True if music is currently playing
    """
    return _player.is_playing()


def cleanup_music() -> None:
    """
    Public interface for cleanup.
    Call this during system shutdown.
    """
    _player.cleanup()
