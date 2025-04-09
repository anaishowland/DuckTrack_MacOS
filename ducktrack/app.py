import os
import sys
from platform import system

from PyQt6.QtCore import QTimer, pyqtSlot, QMetaObject, Q_ARG, Qt
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog,
                             QFormLayout, QLabel, QLineEdit, QMenu,
                             QMessageBox, QPushButton, QSystemTrayIcon,
                             QTextEdit, QVBoxLayout, QWidget)
from pynput import mouse

# Import AppKit for macOS specific window fetching
if system() == "Darwin":
    from AppKit import NSWorkspace

from .obs_client import close_obs, is_obs_running, open_obs
from .playback import Player, get_latest_recording
from .recorder import Recorder
from .util import get_recordings_dir, open_file


class TitleDescriptionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Recording Details")

        layout = QVBoxLayout(self)

        self.form_layout = QFormLayout()

        self.title_label = QLabel("Title:")
        self.title_input = QLineEdit(self)
        self.form_layout.addRow(self.title_label, self.title_input)

        self.description_label = QLabel("Description:")
        self.description_input = QTextEdit(self)
        self.form_layout.addRow(self.description_label, self.description_input)

        layout.addLayout(self.form_layout)

        self.submit_button = QPushButton("Save", self)
        self.submit_button.clicked.connect(self.accept)
        layout.addWidget(self.submit_button)

    def get_values(self):
        return self.title_input.text(), self.description_input.toPlainText()

class MainInterface(QWidget):
    def __init__(self, app: QApplication):
        super().__init__()
        self.tray = QSystemTrayIcon(QIcon(resource_path("assets/duck.png")))
        self.tray.show()
                
        self.app = app
        
        self.init_tray()
        self.init_window()
        
        # UI Polling Timer setup
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(500)  # Poll every 500ms
        self.poll_timer.timeout.connect(self._poll_ui_state)
        self.last_known_window_title = None

        if not is_obs_running():
            self.obs_process = open_obs()

    def init_window(self):
        self.setWindowTitle("DuckTrack")
        layout = QVBoxLayout(self)
        
        self.toggle_record_button = QPushButton("Start Recording", self)
        self.toggle_record_button.clicked.connect(self.toggle_record)
        layout.addWidget(self.toggle_record_button)
        
        self.toggle_pause_button = QPushButton("Pause Recording", self)
        self.toggle_pause_button.clicked.connect(self.toggle_pause)
        self.toggle_pause_button.setEnabled(False)
        layout.addWidget(self.toggle_pause_button)
        
        self.show_recordings_button = QPushButton("Show Recordings", self)
        self.show_recordings_button.clicked.connect(lambda: open_file(get_recordings_dir()))
        layout.addWidget(self.show_recordings_button)
        
        self.play_latest_button = QPushButton("Play Latest Recording", self)
        self.play_latest_button.clicked.connect(self.play_latest_recording)
        layout.addWidget(self.play_latest_button)
        
        self.play_custom_button = QPushButton("Play Custom Recording", self)
        self.play_custom_button.clicked.connect(self.play_custom_recording)
        layout.addWidget(self.play_custom_button)
        
        self.replay_recording_button = QPushButton("Replay Recording", self)
        self.replay_recording_button.clicked.connect(self.replay_recording)
        self.replay_recording_button.setEnabled(False)
        layout.addWidget(self.replay_recording_button)
        
        self.quit_button = QPushButton("Quit", self)
        self.quit_button.clicked.connect(self.quit)
        layout.addWidget(self.quit_button)
        
        self.natural_scrolling_checkbox = QCheckBox("Natural Scrolling", self, checked=system() == "Darwin")
        layout.addWidget(self.natural_scrolling_checkbox)

        self.natural_scrolling_checkbox.stateChanged.connect(self.toggle_natural_scrolling)
        
        self.setLayout(layout)
        
    def init_tray(self):
        self.menu = QMenu()
        self.tray.setContextMenu(self.menu)

        self.toggle_record_action = QAction("Start Recording")
        self.toggle_record_action.triggered.connect(self.toggle_record)
        self.menu.addAction(self.toggle_record_action)

        self.toggle_pause_action = QAction("Pause Recording")
        self.toggle_pause_action.triggered.connect(self.toggle_pause)
        self.toggle_pause_action.setVisible(False)
        self.menu.addAction(self.toggle_pause_action)
        
        self.show_recordings_action = QAction("Show Recordings")
        self.show_recordings_action.triggered.connect(lambda: open_file(get_recordings_dir()))
        self.menu.addAction(self.show_recordings_action)
        
        self.play_latest_action = QAction("Play Latest Recording")
        self.play_latest_action.triggered.connect(self.play_latest_recording)
        self.menu.addAction(self.play_latest_action)

        self.play_custom_action = QAction("Play Custom Recording")
        self.play_custom_action.triggered.connect(self.play_custom_recording)
        self.menu.addAction(self.play_custom_action)
        
        self.replay_recording_action = QAction("Replay Recording")
        self.replay_recording_action.triggered.connect(self.replay_recording)
        self.menu.addAction(self.replay_recording_action)
        self.replay_recording_action.setVisible(False)

        self.quit_action = QAction("Quit")
        self.quit_action.triggered.connect(self.quit)
        self.menu.addAction(self.quit_action)
        
        self.menu.addSeparator()
        
        self.natural_scrolling_option = QAction("Natural Scrolling", checkable=True, checked=system() == "Darwin")
        self.natural_scrolling_option.triggered.connect(self.toggle_natural_scrolling)
        self.menu.addAction(self.natural_scrolling_option)
        
    @pyqtSlot()
    def replay_recording(self):
        player = Player()
        if hasattr(self, "last_played_recording_path"):
            player.play(self.last_played_recording_path)
        else:
            self.display_error_message("No recording has been played yet!")

    @pyqtSlot()
    def play_latest_recording(self):
        player = Player()
        recording_path = get_latest_recording()
        self.last_played_recording_path = recording_path
        self.replay_recording_action.setVisible(True)
        self.replay_recording_button.setEnabled(True)
        player.play(recording_path)

    @pyqtSlot()
    def play_custom_recording(self):
        player = Player()
        directory = QFileDialog.getExistingDirectory(None, "Select Recording", get_recordings_dir())
        if directory:
            self.last_played_recording_path = directory
            self.replay_recording_button.setEnabled(True)
            self.replay_recording_action.setVisible(True)
            player.play(directory)

    @pyqtSlot()
    def quit(self):
        if hasattr(self, "recorder_thread"):
            self.toggle_record()
        if hasattr(self, "obs_process"):
            close_obs(self.obs_process)
        self.app.quit()

    def closeEvent(self, event):
        self.quit()

    @pyqtSlot()
    def toggle_natural_scrolling(self):
        sender = self.sender()

        if sender == self.natural_scrolling_checkbox:
            state = self.natural_scrolling_checkbox.isChecked()
            self.natural_scrolling_option.setChecked(state)
        else:
            state = self.natural_scrolling_option.isChecked()
            self.natural_scrolling_checkbox.setChecked(state)
            if hasattr(self, "recorder_thread"):
                self.recorder_thread.set_natural_scrolling(state)

    @pyqtSlot()
    def toggle_pause(self):
        if self.recorder_thread._is_paused:
            self.recorder_thread.resume_recording()
            self.toggle_pause_action.setText("Pause Recording")
            self.toggle_pause_button.setText("Pause Recording")
        else:
            self.recorder_thread.pause_recording()
            self.toggle_pause_action.setText("Resume Recording")
            self.toggle_pause_button.setText("Resume Recording")

    @pyqtSlot()
    def toggle_record(self):
        if hasattr(self, "recorder_thread") and self.recorder_thread.is_recording():
            self.poll_timer.stop() # Stop polling
            self.recorder_thread.stop_recording()
        else:
            natural_scrolling = self.natural_scrolling_checkbox.isChecked()
            self.recorder_thread = Recorder(natural_scrolling)
            self.recorder_thread.recording_stopped.connect(self.handle_recording_stopped)
            self.recorder_thread.start()

            self.toggle_record_button.setText("Stop Recording")
            self.toggle_record_action.setText("Stop Recording")
            self.toggle_pause_button.setEnabled(True)
            self.toggle_pause_action.setVisible(True)

            # Start polling
            self.last_known_window_title = None # Reset last known title
            self._poll_ui_state() # Initial poll to capture starting state
            self.poll_timer.start()

    @pyqtSlot()
    def handle_recording_stopped(self):
        self.update_menu(False)

    def update_menu(self, is_recording: bool):
        self.toggle_record_button.setText("Stop Recording" if is_recording else "Start Recording")
        self.toggle_record_action.setText("Stop Recording" if is_recording else "Start Recording")
        
        self.toggle_pause_button.setEnabled(is_recording)
        self.toggle_pause_action.setVisible(is_recording)

    def display_error_message(self, message: str):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setText(message)
        msg.setWindowTitle("Error")
        msg.exec()

    # Replacement _poll_ui_state method with try/except
    def _poll_ui_state(self):
        # Check existence of thread first
        if not hasattr(self, "recorder_thread"):
            return

        try:
            # Check recording and paused state, catching AttributeError if methods aren't ready
            is_recording = self.recorder_thread.is_recording()
            is_paused = self.recorder_thread.is_paused()
            if not is_recording or is_paused:
                return # Don't poll if not recording or paused
        except AttributeError:
             # Method likely not available yet due to thread timing, skip this poll cycle
             return

        try:
            window_title = ""
            app_name = "Unknown"

            # Use AppKit for macOS
            if system() == "Darwin":
                try:
                    workspace = NSWorkspace.sharedWorkspace()
                    active_app = workspace.frontmostApplication()
                    if active_app:
                        app_name = active_app.localizedName()
                        # Getting window title requires more complex accessibility API interaction
                        # For now, let's focus on getting the app name reliably.
                        # We can refine window title fetching later if needed.
                        # Simplified: Use app name as placeholder title if real title is hard.
                        window_title = app_name
                except Exception as e:
                    print(f"Error getting active app info via AppKit: {e}")
            # else:
                # Potentially add back pygetwindow or other methods for Windows/Linux here
                # For now, non-macOS will report Unknown/empty string
                # active_window = gw.getActiveWindow()
                # window_title = active_window.title if active_window else ""

            # Check if app or title changed
            current_focus = (app_name, window_title)
            last_focus = getattr(self, '_last_focus_info', (None, None))

            if current_focus != last_focus:
                self._last_focus_info = current_focus # Store tuple

                # Restore mouse position fetching
                mouse_pos = mouse.Controller().position
                mouse_x, mouse_y = mouse_pos[0], mouse_pos[1]

                # Send event data to the recorder thread
                event_data = {
                    "window_title": window_title,
                    "app_name": app_name,
                    "x": mouse_x,
                    "y": mouse_y
                }
                QMetaObject.invokeMethod(
                    self.recorder_thread,
                    "record_window_focus",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(dict, event_data)
                )

        except AttributeError: # Catch potential AttributeError from mouse.Controller()
            # pynput might not be fully initialized yet
            return
        except Exception as e:
            print(f"Error polling UI state: {e}")

def resource_path(relative_path: str) -> str:
    if hasattr(sys, '_MEIPASS'):
        base_path = getattr(sys, "_MEIPASS")
    else:
        base_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')

    return os.path.join(base_path, relative_path)