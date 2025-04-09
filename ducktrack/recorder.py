import json
import os
import time
from datetime import datetime
from platform import system
from queue import Queue, Empty
import logging

from pynput import keyboard, mouse
from pynput.keyboard import KeyCode
from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot

from .metadata import MetadataManager
from .obs_client import OBSClient
from .util import fix_windows_dpi_scaling, get_recordings_dir

class Recorder(QThread):
    """
    Makes recordings.
    """
    
    recording_stopped = pyqtSignal()
    # Signal to potentially inform main thread about focus (optional)
    # focus_changed = pyqtSignal(dict)

    def __init__(self, natural_scrolling: bool):
        super().__init__()
        
        if system() == "Windows":
            fix_windows_dpi_scaling()
            
        self.recording_path = self._get_recording_path()
        self.mouse_buttons_pressed = set()
        self.natural_scrolling = natural_scrolling
        
        self._is_recording = False
        self._is_paused = False
        
        self.event_queue = Queue()
        self.events_file = None
        
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
        
        # Initialize managers later in run() or ensure thread safety if needed earlier
        self.metadata_manager = None
        self.obs_client = None

        # Listeners setup
        # Listeners are initialized here but started in run()
        self.mouse_listener = mouse.Listener(
            on_move=self.on_move,
            on_click=self.on_click,
            on_scroll=self.on_scroll
            # Removed on_press from mouse listener, handled by keyboard listener
        )

        self.keyboard_listener = keyboard.Listener(
            on_press=self.on_press,
            on_release=self.on_release)

    def on_move(self, x, y):
        if not self._is_paused:
            self.event_queue.put({"time_stamp": time.perf_counter(), 
                                  "action": "move", 
                                  "x": x, 
                                  "y": y}, block=False)
        
    def on_click(self, x, y, button, pressed):
        if not self._is_paused:
            if pressed:
                self.mouse_buttons_pressed.add(button)
            else:
                self.mouse_buttons_pressed.discard(button)
            self.event_queue.put({
                "time_stamp": time.perf_counter(),
                "action": "click",
                "x": x,
                "y": y,
                "button": button.name,
                "pressed": pressed
            }, block=False)
        
    def on_scroll(self, x, y, dx, dy):
        if not self._is_paused:
            self.event_queue.put({"time_stamp": time.perf_counter(), 
                                  "action": "scroll", 
                                  "x": x, 
                                  "y": y, 
                                  "dx": dx, 
                                  "dy": dy}, block=False)
    
    def on_press(self, key):
        if not self._is_paused:
            self.event_queue.put({"time_stamp": time.perf_counter(), 
                                  "action": "press", 
                                  "name": key.char if type(key) == KeyCode else key.name}, block=False)

    def on_release(self, key):
        if not self._is_paused:
            self.event_queue.put({"time_stamp": time.perf_counter(), 
                                  "action": "release", 
                                  "name": key.char if type(key) == KeyCode else key.name}, block=False)
    
    def run(self):
        self._is_recording = True
        self._is_paused = False
        self.mouse_buttons_pressed.clear()

        try:
            self.events_file = open(os.path.join(self.recording_path, "events.jsonl"), "a")

            self.metadata_manager = MetadataManager(
                recording_path=self.recording_path,
                natural_scrolling=self.natural_scrolling
            )
            self.obs_client = OBSClient(
                recording_path=self.recording_path,
                metadata=self.metadata_manager.metadata
            )

            self.metadata_manager.collect()
            self.obs_client.start_recording()

            self.mouse_listener.start()
            # Temporarily disable keyboard listener
            # self.keyboard_listener.start()

            while self._is_recording:
                try:
                    event = self.event_queue.get(timeout=0.1)
                    self.events_file.write(json.dumps(event) + "\n")
                    self.events_file.flush()
                except Empty:
                    pass
                except Exception as e:
                    logging.error(f"Error in recorder run loop: {e}")
                    time.sleep(0.1)

        except Exception as e:
            logging.error(f"Error initializing recorder: {e}")
        finally:
            self._cleanup()

    def _cleanup(self):
        logging.debug("Recorder cleanup started.")
        if hasattr(self, 'mouse_listener') and self.mouse_listener.is_alive():
            try:
                self.mouse_listener.stop()
                self.mouse_listener.join(timeout=1.0)
            except Exception as e:
                logging.error(f"Error stopping mouse listener: {e}")
        # Temporarily disable keyboard listener cleanup
        # if hasattr(self, 'keyboard_listener') and self.keyboard_listener.is_alive():
        #     try:
        #         self.keyboard_listener.stop()
        #         self.keyboard_listener.join(timeout=1.0)
        #     except Exception as e:
        #         logging.error(f"Error stopping keyboard listener: {e}")

        try:
            while not self.event_queue.empty():
                event = self.event_queue.get_nowait()
                if self.events_file and not self.events_file.closed:
                    self.events_file.write(json.dumps(event) + "\n")
            if self.events_file and not self.events_file.closed:
                self.events_file.flush()
        except Exception as e:
             logging.error(f"Error flushing event queue during cleanup: {e}")

        if self.metadata_manager:
            self.metadata_manager.end_collect()
        if self.obs_client:
            try:
                self.obs_client.stop_recording()
                if self.metadata_manager:
                     self.metadata_manager.add_obs_record_state_timings(self.obs_client.record_state_events)
                # Restore the original OBS profile
                self.obs_client.restore_profile()
            except Exception as e:
                 logging.error(f"Error stopping OBS recording or restoring profile: {e}")

        if self.events_file and not self.events_file.closed:
            self.events_file.close()
        if self.metadata_manager:
            self.metadata_manager.save_metadata()

        logging.debug("Recorder cleanup finished.")
        self.recording_stopped.emit()

    def stop_recording(self):
        if self._is_recording:
            logging.info("Stopping recording...")
            self._is_recording = False

    def toggle_pause(self):
        self._is_paused = not self._is_paused
        state = "paused" if self._is_paused else "resumed"
        logging.info(f"Recording {state}.")
        self.event_queue.put({
            "time_stamp": time.perf_counter(),
            "action": "pause" if self._is_paused else "resume"
        }, block=False)
        if self.obs_client:
            try:
                if self._is_paused:
                    self.obs_client.pause_recording()
                else:
                    self.obs_client.resume_recording()
            except Exception as e:
                logging.error(f"Error toggling OBS pause state: {e}")

    def _get_recording_path(self) -> str:
        recordings_dir = get_recordings_dir()
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = os.path.join(recordings_dir, timestamp)
        os.makedirs(path, exist_ok=True)
        return path

    def set_natural_scrolling(self, natural_scrolling: bool):
        self.natural_scrolling = natural_scrolling
        if self.metadata_manager:
            self.metadata_manager.set_scroll_direction(self.natural_scrolling)

    # Methods for main thread to check state
    def is_recording(self) -> bool:
        return self._is_recording

    def is_paused(self) -> bool:
        return self._is_paused

    # Slot to receive window focus data from the main thread
    @pyqtSlot(dict)
    def record_window_focus(self, event_data):
        if not self._is_recording or self._is_paused:
            return

        try:
            # Determine current mouse button state
            button_name = None
            pressed = False
            if self.mouse_buttons_pressed:
                button = next(iter(self.mouse_buttons_pressed))
                button_name = button.name
                pressed = True

            event = {
                "time_stamp": time.perf_counter(),
                "action": "window_focus",
                "app_name": "Unknown",
                "window_title": event_data.get("window_title", ""),
                "x": event_data.get("x"),
                "y": event_data.get("y"),
                "button": button_name,
                "pressed": pressed
            }
            self.event_queue.put(event, block=False)
            logging.debug(f"Window focus event queued: {event}")
        except Exception as e:
            logging.error(f"Error processing window focus event: {e}")

    # pynput callbacks
    def on_move(self, x, y):
        if not self._is_paused:
            self.event_queue.put({"time_stamp": time.perf_counter(),
                                  "action": "move",
                                  "x": x,
                                  "y": y}, block=False)

    def on_click(self, x, y, button, pressed):
        if not self._is_paused:
            # Update the set of currently pressed buttons
            if pressed:
                self.mouse_buttons_pressed.add(button)
            else:
                self.mouse_buttons_pressed.discard(button)

            # Queue the click event
            self.event_queue.put({
                "time_stamp": time.perf_counter(),
                "action": "click",
                "x": x,
                "y": y,
                "button": button.name,
                "pressed": pressed
            }, block=False)

    def on_scroll(self, x, y, dx, dy):
        if not self._is_paused:
            self.event_queue.put({"time_stamp": time.perf_counter(),
                                  "action": "scroll",
                                  "x": x,
                                  "y": y,
                                  "dx": dx,
                                  "dy": dy}, block=False)

    def on_press(self, key):
        if not self._is_paused:
            self.event_queue.put({"time_stamp": time.perf_counter(),
                                  "action": "press",
                                  "name": key.char if type(key) == KeyCode else key.name}, block=False)

    def on_release(self, key):
        if not self._is_paused:
            self.event_queue.put({"time_stamp": time.perf_counter(),
                                  "action": "release",
                                  "name": key.char if type(key) == KeyCode else key.name}, block=False)
    # End pynput callbacks