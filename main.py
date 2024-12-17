import os
import sys
import logging
from PySide6.QtWidgets import (
    QMainWindow,
    QSystemTrayIcon,
    QMenu,
    QApplication,
    QTextEdit,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QFrame,
    QWidget,
    QCheckBox,
    QLineEdit,
    QSystemTrayIcon,
    QMenu,
)
from PySide6.QtGui import QIcon, QIntValidator
from PySide6.QtCore import QSettings, QProcess, QTimer

# Set up logging
logging.config.dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s :: %(levelname)s :: %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
            },
        },
        "loggers": {
            "": {
                "handlers": ["console"],
                "level": "DEBUG",
            },
        },
    }
)

logger = logging.getLogger(__name__)

logger.debug(sys.executable)
logger.debug(sys.version)


class MainWindow(QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()

        # set window title and icon
        self.setWindowTitle("Dashb")
        self.setWindowIcon(QIcon("icon.svg"))

        # Create a tray icon
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon("icon.svg"))
        self.tray_icon.setToolTip("Dashb")
        self.tray_icon.show()

        # tray menu
        self.tray_menu = QMenu()
        self.tray_icon.setContextMenu(self.tray_menu)
        quit_action = self.tray_menu.addAction("Quit")
        quit_action.triggered.connect(QApplication.quit)
        # click tray icon to show window
        self.tray_icon.activated.connect(
            lambda reason: reason == QSystemTrayIcon.ActivationReason.Trigger
            and self.show()
        )

        # Create a button for start/stop the server
        self.btn_server_toggle = QPushButton("Start Server", self)
        self.btn_server_toggle.setCheckable(True)
        self.btn_server_toggle.clicked.connect(self.on_server_toggle)

        # Create a button for opening settings
        self.button_settings = QPushButton("Settings", self)
        self.button_settings.clicked.connect(lambda: self.settings_window.show())
        self.settings_window = SettingsWindow()

        # Create a button for quitting the application
        self.button_quit = QPushButton("Quit", self)
        self.button_quit.clicked.connect(QApplication.quit)

        # Create a read-only text for showing server log
        self.text_log = QTextEdit(self)
        self.text_log.setReadOnly(True)

        # Create the layout for buttons
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.btn_server_toggle)
        button_layout.addStretch()  # Spacer to push button to the right
        button_layout.addWidget(self.button_settings)
        button_layout.addWidget(self.button_quit)

        # Create a separator (horizontal line)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)

        # Main layout
        main_layout = QVBoxLayout()
        main_layout.addLayout(button_layout)  # Add button layout to main layout
        main_layout.addWidget(separator)  # Add separator after the buttons
        main_layout.addWidget(self.text_log)  # Add the log area after the separator

        # Create a central widget and set the layout to it
        central_widget = QWidget(self)
        central_widget.setLayout(main_layout)

        # Set the central widget to the QMainWindow
        self.setCentralWidget(central_widget)

        # Start the server
        self.btn_server_toggle.click()

    def start_server(self):
        """Start the server."""
        if (
            hasattr(self, "server_process")
            and self.server_process.state() != QProcess.NotRunning
        ):
            logger.warning("Server process is already running")
            return

        host = self.settings_window.settings.value("host", "0.0.0.0", type=str)
        port = self.settings_window.settings.value("port", 8080, type=int)
        username = self.settings_window.settings.value("username", "", type=str)
        password = self.settings_window.settings.value("password", "", type=str)

        # Run server.py in QProcess
        self.server_process = QProcess()
        self.server_process.setProgram(sys.executable)

        # pass config as environment vars to the server.py script
        # env = QProcessEnvironment.systemEnvironment()
        env = self.server_process.processEnvironment()
        env.insert("HOST", host)
        env.insert("PORT", str(port))
        env.insert("USERNAME", username)
        env.insert("PASSWORD", password)
        self.server_process.setProcessEnvironment(env)

        self.server_process.setArguments(["server.py"])

        # Redirect standard output and error to log_message
        self.server_process.readyReadStandardOutput.connect(
            lambda: self.log_message(
                self.server_process.readAllStandardOutput().data().decode()
            )
        )
        self.server_process.readyReadStandardError.connect(
            lambda: self.log_message(
                self.server_process.readAllStandardError().data().decode()
            )
        )
        # Handle server process started and finished signals
        self.server_process.started.connect(self.on_server_started)
        self.server_process.finished.connect(self.on_server_stopped)

        logger.info(f"Starting server at {host}:{port}")
        self.server_process.start()

    def stop_server(self):
        """Stop the server."""
        if not hasattr(self, "server_process"):
            logger.warning("Server process not found")
            return
        if self.server_process.state() == QProcess.NotRunning:
            logger.warning("Server process is not running")
            return

        if os.name == "nt":
            # On Windows, simply kill the process with no mercy. See https://doc.qt.io/qt-6/qprocess.html#terminate
            self.server_process.kill()
            return

        # Attempt to terminate the process
        logger.info("Terminating server process")
        self.server_process.terminate()

        # Use a QTimer to kill the process after 3 seconds if it doesn't terminate
        self.server_kill_timer = QTimer(self)
        self.server_kill_timer.setSingleShot(True)

        self.server_kill_timer.timeout.connect(self.kill_server)
        self.server_kill_timer.start(3000)

    def kill_server(self):
        if self.server_process.state() != QProcess.NotRunning:
            logger.warning("Killing server process")
            self.server_process.kill()

    def on_server_started(self):
        """Handle server started event."""
        self.btn_server_toggle.setText("Stop Server")
        self.btn_server_toggle.setEnabled(True)
        self.btn_server_toggle.setChecked(True)

    def on_server_stopped(self):
        """Handle server stopped event."""
        if hasattr(self, "server_kill_timer"):
            self.server_kill_timer.stop()
            self.server_kill_timer.deleteLater()

        self.btn_server_toggle.setText("Start Server")
        self.btn_server_toggle.setEnabled(True)
        self.btn_server_toggle.setChecked(False)

    def on_server_toggle(self):
        """Start or stop the server."""
        logger.debug(f"Switch checked: {self.btn_server_toggle.isChecked()}")
        if self.btn_server_toggle.isChecked():
            self.btn_server_toggle.setText("Starting...")
            self.btn_server_toggle.setEnabled(False)
            self.start_server()
        else:
            self.btn_server_toggle.setText("Stopping...")
            self.btn_server_toggle.setEnabled(False)
            self.stop_server()

    # close to tray
    def closeEvent(self, event):
        event.ignore()
        self.settings_window.hide()
        self.hide()

    def log_message(self, message: str):
        """Logs message to the text area."""
        logging.info(message)
        self.text_log.append(message)


class SettingsWindow(QMainWindow):
    def __init__(self):
        super(SettingsWindow, self).__init__()

        # Set window title and icon
        self.setWindowTitle("Settings")
        self.setWindowIcon(QIcon("icon.svg"))

        # Initialize QSettings
        self.settings = QSettings("MyApp", "Dashb")

        # Create a QLineEdit with label for server host
        self.host_label = QLabel("Host:", self)
        self.host_input = QLineEdit(self)
        self.host_input.setFixedWidth(100)

        # Create a QLineEdit with label for server port
        self.port_label = QLabel("Port:", self)
        self.port_input = QLineEdit(self)
        self.port_input.setFixedWidth(50)
        self.port_input.setValidator(QIntValidator(1, 65535))  # 1-65535 numbers only

        # create a checkbox for Basic Auth
        self.basic_auth = QCheckBox("Basic Auth", self)
        self.basic_auth.toggled.connect(self.on_basic_auth_toggle)

        # Create a QLineEdit with label for username
        self.username_label = QLabel("Username:", self)
        self.username_input = QLineEdit(self)
        self.username_input.setFixedWidth(100)

        # Create a QLineEdit with label for password
        self.password_label = QLabel("Password:", self)
        self.password_input = QLineEdit(self)
        self.password_input.setFixedWidth(100)
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)

        # Create a check box for run on startup
        self.run_on_startup = QCheckBox("Run on startup", self)

        # Create a button for canceling settings
        self.button_cancel = QPushButton("Cancel", self)
        self.button_cancel.clicked.connect(self.close)

        # Create a button for saving settings
        self.button_save = QPushButton("Save", self)
        self.button_save.clicked.connect(self.save_settings)

        # Create the form layout for the label and input
        port_settings_layout = QFormLayout()
        port_settings_layout.addRow(self.host_label, self.host_input)
        port_settings_layout.addRow(self.port_label, self.port_input)

        auth_settings_layout = QFormLayout()
        auth_settings_layout.addRow(self.username_label, self.username_input)
        auth_settings_layout.addRow(self.password_label, self.password_input)

        # Create the layout for buttons (Save and Cancel)
        button_layout = QHBoxLayout()
        button_layout.addStretch()  # Add spacer to push buttons to the right
        button_layout.addWidget(self.button_cancel)
        button_layout.addWidget(self.button_save)

        # Main layout
        main_layout = QVBoxLayout()
        main_layout.addLayout(port_settings_layout)
        main_layout.addWidget(self.basic_auth)
        main_layout.addLayout(auth_settings_layout)
        main_layout.addWidget(self.run_on_startup)
        main_layout.addStretch()  # Add spacer to push buttons to the bottom
        main_layout.addLayout(button_layout)  # Add the button layout

        # Set the layout to the central widget
        central_widget = QWidget(self)
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

        # Load saved settings
        self.load_settings()

    def on_basic_auth_toggle(self, checked):
        """Toggle the username and password input fields."""
        self.username_input.setEnabled(checked)
        self.password_input.setEnabled(checked)

    def save_settings(self):
        """Save settings to persistent storage."""
        self.settings.setValue("host", self.host_input.text())
        self.settings.setValue("port", self.port_input.text())
        self.settings.setValue("basic_auth", self.basic_auth.isChecked())
        self.settings.setValue("username", self.username_input.text())
        self.settings.setValue("password", self.password_input.text())
        self.settings.setValue("run_on_startup", self.run_on_startup.isChecked())
        self.close()

    def load_settings(self):
        """Load settings from persistent storage."""
        host = self.settings.value("host", "0.0.0.0", type=str)
        port = self.settings.value("port", "8080", type=str)
        basic_auth = self.settings.value("basic_auth", False, type=bool)
        username = self.settings.value("username", "", type=str)
        password = self.settings.value("password", "", type=str)
        run_on_startup = self.settings.value("run_on_startup", False, type=bool)

        self.host_input.setText(host)
        self.port_input.setText(port)
        self.basic_auth.setChecked(basic_auth)
        self.username_input.setText(username)
        self.password_input.setText(password)
        self.username_input.setEnabled(basic_auth)
        self.password_input.setEnabled(basic_auth)
        self.run_on_startup.setChecked(run_on_startup)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.exec()
    sys.exit()
