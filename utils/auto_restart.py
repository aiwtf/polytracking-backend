"""
Auto-restart monitor for Polytracking services.
Monitors main API and collector processes, auto-restarts on crash.
"""
import os
import sys
import time
import psutil
import logging
from datetime import datetime
from pathlib import Path

# Setup logging
log_dir = Path(__file__).parent.parent / "logs"
log_dir.mkdir(exist_ok=True)
log_file = log_dir / "restart.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class ProcessMonitor:
    """Monitor and restart processes on failure."""
    
    def __init__(self, name, command, cwd=None):
        self.name = name
        self.command = command
        self.cwd = cwd or os.getcwd()
        self.process = None
        self.restart_count = 0
        self.last_restart = None
    
    def is_alive(self):
        """Check if process is running."""
        if self.process is None:
            return False
        try:
            proc = psutil.Process(self.process.pid)
            return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
    
    def start(self):
        """Start the process."""
        import subprocess
        try:
            self.process = subprocess.Popen(
                self.command,
                shell=True,
                cwd=self.cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            logger.info(f"[{self.name}] Started (PID: {self.process.pid})")
            return True
        except Exception as e:
            logger.error(f"[{self.name}] Failed to start: {e}")
            return False
    
    def restart(self):
        """Restart the process."""
        self.restart_count += 1
        self.last_restart = datetime.now()
        logger.warning(f"[{self.name}] Restarting (count: {self.restart_count})")
        
        # Kill existing process if still alive
        if self.process:
            try:
                proc = psutil.Process(self.process.pid)
                proc.terminate()
                proc.wait(timeout=5)
            except (psutil.NoSuchProcess, psutil.TimeoutExpired):
                pass
        
        # Start new process
        return self.start()
    
    def check_and_restart(self):
        """Check process health and restart if needed."""
        if not self.is_alive():
            logger.warning(f"[{self.name}] Process not alive, restarting...")
            return self.restart()
        return True


def monitor_services(check_interval=60):
    """
    Main monitoring loop.
    
    Args:
        check_interval: Seconds between health checks (default: 60)
    """
    logger.info("=" * 60)
    logger.info("Polytracking Auto-Restart Monitor Started")
    logger.info("=" * 60)
    
    # Define services to monitor
    backend_dir = Path(__file__).parent.parent
    
    monitors = [
        ProcessMonitor(
            name="API",
            command="uvicorn main:app --host 0.0.0.0 --port 8000",
            cwd=str(backend_dir)
        ),
        ProcessMonitor(
            name="Collector",
            command="python collector.py",
            cwd=str(backend_dir)
        )
    ]
    
    # Start all services
    for monitor in monitors:
        monitor.start()
        time.sleep(2)
    
    # Monitoring loop
    try:
        while True:
            time.sleep(check_interval)
            
            for monitor in monitors:
                monitor.check_and_restart()
            
            # Log status every 10 checks
            if sum(m.restart_count for m in monitors) % 10 == 0:
                logger.info("Status check: All services running")
    
    except KeyboardInterrupt:
        logger.info("Monitor stopped by user")
        # Cleanup
        for monitor in monitors:
            if monitor.process:
                try:
                    proc = psutil.Process(monitor.process.pid)
                    proc.terminate()
                except:
                    pass


if __name__ == "__main__":
    # Check if running on Render (has PORT env var)
    if os.getenv("PORT"):
        logger.info("Running on Render - skipping auto-restart (managed by platform)")
        sys.exit(0)
    
    monitor_services(check_interval=60)
