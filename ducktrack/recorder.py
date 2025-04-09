import json
import os
import time
from datetime import datetime
from platform import system
from queue import Queue, Empty
import logging
import objc # PyObjC might be needed for block callbacks
import sys

from pynput import keyboard, mouse
from pynput.keyboard import KeyCode
from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot

# Import AppKit conditionally for macOS keyboard handling
if system() == "Darwin":
    try:
        from AppKit import NSEvent, NSKeyDownMask, NSKeyUpMask, NSFlagsChangedMask, NSShiftKeyMask, NSControlKeyMask, NSAlternateKeyMask, NSCommandKeyMask
    except ImportError:
        logging.error("PyObjC (AppKit) not found. Keyboard events cannot be recorded on macOS.")
        NSEvent = None # Flag that AppKit is unavailable
else:
    NSEvent = None

# --- Add AppKit to the global scope if available ---
# This makes it accessible within the handler function more reliably
AppKit = sys.modules.get('AppKit', None)

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
        )

        # Initialize pynput keyboard listener ONLY if not macOS or AppKit failed
        self.keyboard_listener = None
        if system() != "Darwin" or not NSEvent:
            logging.info("Using pynput keyboard listener (not macOS or AppKit unavailable).")
            self.keyboard_listener = keyboard.Listener(
                on_press=self.on_press,
                on_release=self.on_release)
        else:
            logging.info("Will use AppKit for macOS keyboard events.")

        self.macos_key_monitor = None # Holder for the NSEvent monitor

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
        self.macos_key_monitor = None # Ensure monitor is reset

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

            print("DEBUG: Starting input listeners/monitors...")
            self.mouse_listener.start()

            if self.keyboard_listener: # Use pynput if available
                self.keyboard_listener.start()
            elif NSEvent and system() == "Darwin": # Use AppKit on macOS if available
                logging.info("Attempting to start AppKit global key monitor.")

                # Define the handler function locally to capture self
                def macos_handler_wrapper(event):
                    # Call the instance method to handle the event
                    return self._macos_key_handler(event)

                # Pass the wrapper function directly
                self.macos_key_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                    (NSKeyDownMask | NSKeyUpMask | NSFlagsChangedMask),
                    macos_handler_wrapper # Pass the wrapper
                )
                # --- DEBUG: Check if monitor was created --- 
                if not self.macos_key_monitor:
                    logging.error("FAILED TO CREATE AppKit global key monitor! Check Accessibility permissions?")
                else:
                    logging.info("AppKit global key monitor object created successfully.")
                # --- END DEBUG ---
            else:
                 logging.warning("No keyboard listener available for this platform.")

            time.sleep(0.1)

            self.obs_client.start_recording()

            while self._is_recording:
                try:
                    event = self.event_queue.get(timeout=0.1)
                    self.events_file.write(json.dumps(event) + "\n")
                    self.events_file.flush() # Force flush after every write
                except Empty:
                    pass
                except Exception as e:
                    logging.error(f"Error in recorder run loop writing event: {e}")
                    time.sleep(0.1)

        except Exception as e:
            logging.error(f"Error initializing or running recorder: {e}")
        finally:
            # Ensure final flush before cleanup attempts
            if self.events_file and not self.events_file.closed:
                 try: self.events_file.flush() 
                 except Exception: pass
            self._cleanup()

    def _cleanup(self):
        logging.debug("Recorder cleanup started.")
        print("DEBUG: Stopping input listeners/monitors...")

        # Stop AppKit monitor first if it exists
        if self.macos_key_monitor:
            try:
                logging.info("Removing AppKit global key monitor.")
                NSEvent.removeMonitor_(self.macos_key_monitor)
                self.macos_key_monitor = None
            except Exception as e:
                logging.error(f"Error removing AppKit monitor: {e}")

        # Stop pynput listeners
        if hasattr(self, 'mouse_listener') and self.mouse_listener.is_alive():
            try:
                self.mouse_listener.stop()
                self.mouse_listener.join(timeout=1.0)
            except Exception as e:
                logging.error(f"Error stopping mouse listener: {e}")
        if self.keyboard_listener and hasattr(self, 'keyboard_listener') and self.keyboard_listener.is_alive():
            try:
                self.keyboard_listener.stop()
                self.keyboard_listener.join(timeout=1.0)
            except Exception as e:
                logging.error(f"Error stopping keyboard listener: {e}")

        # --- Improved Queue Draining --- 
        logging.debug(f"Events left in queue before final drain: {self.event_queue.qsize()}")
        queued_events = []
        while not self.event_queue.empty():
            try:
                queued_events.append(self.event_queue.get_nowait())
            except Empty:
                break # Should not happen with empty() check, but safety first
        logging.debug(f"Drained {len(queued_events)} events from queue.")
        
        if self.events_file and not self.events_file.closed:
             if queued_events:
                 logging.info(f"Writing {len(queued_events)} remaining events to file...")
                 try:
                     for event in queued_events:
                         self.events_file.write(json.dumps(event) + "\n")
                     self.events_file.flush()
                     logging.info("Finished writing remaining events.")
                 except Exception as e:
                    logging.error(f"Error writing remaining events during cleanup: {e}")
        # --- End Improved Queue Draining ---

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

            # Ensure app_name and window_title from event_data are used
            event = {
                "time_stamp": time.perf_counter(),
                "action": "window_focus",
                "app_name": event_data.get("app_name", "Unknown"), # Use fetched name
                "window_title": event_data.get("window_title", ""), # Use fetched title (placeholder)
                "x": event_data.get("x"),
                "y": event_data.get("y"),
                "button": button_name,
                "pressed": pressed
            }
            self.event_queue.put(event, block=False)
            # logging.debug(f"Window focus event queued: {event}") # Can be noisy
        except Exception as e:
            logging.error(f"Error processing window focus event: {e}")

    # --- macOS Specific Key Handling ---
    def _macos_key_handler(self, event):
        if not AppKit:
            return event
        if not self._is_recording or self._is_paused:
            return event

        try:
            # Use integer type codes
            event_type = int(event.type()) # Ensure integer type
            key_code = event.keyCode()
            modifierFlags = event.modifierFlags()

            action = None
            final_name = None 

            if event_type == 10: # KeyDown
                action = "press"
            elif event_type == 11: # KeyUp
                action = "release"
            elif event_type == 12: # FlagsChanged
                modifier_map = {
                    54: 'right_cmd', 55: 'cmd', 56: 'shift', 60: 'right_shift', 
                    58: 'alt', 61: 'right_alt', 59: 'ctrl', 62: 'right_ctrl', 
                    63: 'fn', 57: 'caps_lock'
                }
                mod_name = modifier_map.get(key_code)
                if mod_name:
                    # Check current flag state. Need AppKit constants here.
                    try: 
                        flag_map = {
                             'shift': AppKit.NSEvent.NSShiftKeyMask, 'right_shift': AppKit.NSEvent.NSShiftKeyMask,
                             'cmd': AppKit.NSEvent.NSCommandKeyMask, 'right_cmd': AppKit.NSEvent.NSCommandKeyMask,
                             'alt': AppKit.NSEvent.NSAlternateKeyMask, 'right_alt': AppKit.NSEvent.NSAlternateKeyMask,
                             'ctrl': AppKit.NSEvent.NSControlKeyMask, 'right_ctrl': AppKit.NSEvent.NSControlKeyMask,
                             'fn': AppKit.NSEvent.NSFunctionKeyMask, 
                             'caps_lock': AppKit.NSEvent.NSAlphaShiftKeyMask
                        }
                        modifier_flag = flag_map.get(mod_name)
                        if modifier_flag:
                            is_pressed = (modifierFlags & modifier_flag) != 0
                            action = "press" if is_pressed else "release"
                            final_name = mod_name
                        else: action = None 
                    except AttributeError as e_flags: # Catch if AppKit constants fail
                         print(f"ERROR accessing AppKit flag constants in handler: {e_flags}")
                         action = None
                else: action = None
            else: return event

            # Get character info only for KeyDown/KeyUp
            chars = None
            chars_shifted = None
            if event_type == 10 or event_type == 11:
                if not final_name: # If not already determined as a modifier
                    chars = event.charactersIgnoringModifiers()
                    chars_shifted = event.characters()
                    temp_name = chars_shifted if chars_shifted else f"KeyCode_{key_code}"
                    final_name = chars if chars and len(chars) == 1 and chars.isprintable() else temp_name
                    key_map = {
                        53: 'esc', 49: 'space', 36: 'enter', 51: 'backspace', 48: 'tab',
                        123: 'left', 124: 'right', 125: 'down', 126: 'up'
                    }
                    if not (chars and len(chars) == 1 and chars.isprintable()):
                        final_name = key_map.get(key_code, f"KeyCode_{key_code}")
            
            # Only queue if we determined a valid action and name
            if action and final_name:
                key_event = {
                    "time_stamp": time.perf_counter(),
                    "action": action,
                    "name": final_name,
                    "macos_key_code": key_code,
                    "macos_raw_chars": chars if chars is not None else None,
                    "macos_chars_shifted": chars_shifted if chars_shifted is not None else None,
                    "macos_modifierFlags": int(modifierFlags) 
                }
                self.event_queue.put(key_event, block=False)

        except Exception as e:
            logging.error(f"Error handling detailed macOS key event: {e}")

        return event

    # --- pynput Callbacks (used for mouse and non-macOS keys) ---
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

    # on_press/on_release only used for non-macOS or if AppKit fails
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
    # --- End pynput Callbacks ---