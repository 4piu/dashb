import os
import sys
import logging
import logging.config
from pathlib import Path
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
    QFileDialog,
    QMessageBox,
)
from PySide6.QtGui import QIcon, QIntValidator, QDesktopServices, QGuiApplication
from PySide6.QtCore import QSettings, QProcess, QProcessEnvironment, QTimer, QUrl, Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from dashb.paths import app_root
from dashb import startup
from dashb.theme import default_user_theme_root
from dashb.theme_install import (
    ThemeInstallError,
    install_theme_from_zip,
    theme_exists,
    theme_id_in_zip,
)

ICON_DIR = app_root() / "dashb" / "assets"


def _theme_icon_path() -> Path:
    """Pick the icon variant that stays legible against the current OS tray/title
    bar background: a light (near-white) glyph for a dark system theme, a dark
    glyph for a light one.
    """
    scheme = QGuiApplication.styleHints().colorScheme()
    name = "icon-dark.svg" if scheme == Qt.ColorScheme.Dark else "icon-light.svg"
    return ICON_DIR / name


SINGLE_INSTANCE_KEY = "dashb-gui-singleton"

# Set up logging
logging.config.dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s %(filename)s(%(lineno)d) [%(levelname)s] %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
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
        self.setWindowIcon(QIcon(str(_theme_icon_path())))

        # Create a tray icon
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon(str(_theme_icon_path())))
        self.tray_icon.setToolTip("Dashb")
        self.tray_icon.show()

        # Keep the tray icon legible if the user switches OS theme while the
        # app is running (e.g. Windows' scheduled light/dark switch).
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._update_tray_icon)

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

        # Create a read-only text for showing server log
        self.text_log = QTextEdit(self)
        self.text_log.setReadOnly(True)

        # Create a button for start/stop the server
        self.btn_server_toggle = QPushButton("Start Server", self)
        self.btn_server_toggle.setCheckable(True)
        self.btn_server_toggle.clicked.connect(self.on_server_toggle)

        # Create a button for clearing the log
        self.button_clear_log = QPushButton("Clear Log", self)
        self.button_clear_log.clicked.connect(self.text_log.clear)

        # Create a button for opening the user themes folder
        self.button_open_themes_folder = QPushButton("Open Themes Folder", self)
        self.button_open_themes_folder.clicked.connect(self.on_open_themes_folder)

        # Create a button for installing a theme from a zip file
        self.button_install_theme = QPushButton("Install Theme...", self)
        self.button_install_theme.clicked.connect(self.on_install_theme)

        # Create a button for opening settings
        self.button_settings = QPushButton("Settings", self)
        self.button_settings.clicked.connect(lambda: self.settings_window.show())
        self.settings_window = SettingsWindow()

        # Create a button for quitting the application
        self.button_quit = QPushButton("Quit", self)
        self.button_quit.clicked.connect(QApplication.quit)

        # Give every button some breathing room instead of a wall of edge-to-edge text.
        central_widget = QWidget(self)
        central_widget.setStyleSheet("QPushButton { padding: 6px 14px; }")

        # Row 1: server lifecycle controls, with Settings pulled to the far side
        # so it doesn't compete for attention with the primary Start/Stop action.
        server_row = QHBoxLayout()
        server_row.setSpacing(8)
        server_row.addWidget(self.btn_server_toggle)
        server_row.addWidget(self.button_clear_log)
        server_row.addStretch()
        server_row.addWidget(self.button_settings)

        # Row 2: theme management, with Quit isolated on the far side so it isn't
        # adjacent to the frequently-used theme buttons (avoids accidental clicks).
        theme_row = QHBoxLayout()
        theme_row.setSpacing(8)
        theme_row.addWidget(self.button_open_themes_folder)
        theme_row.addWidget(self.button_install_theme)
        theme_row.addStretch()
        theme_row.addWidget(self.button_quit)

        button_layout = QVBoxLayout()
        button_layout.setSpacing(8)
        button_layout.addLayout(server_row)
        button_layout.addLayout(theme_row)

        # Create a separator (horizontal line)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)

        # Main layout
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)
        main_layout.addLayout(button_layout)  # Add button layout to main layout
        main_layout.addWidget(separator)  # Add separator after the buttons
        main_layout.addWidget(self.text_log)  # Add the log area after the separator

        # Set the layout to the central widget
        central_widget.setLayout(main_layout)

        # Set the central widget to the QMainWindow
        self.setCentralWidget(central_widget)
        self.resize(560, 420)

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
        basic_auth = self.settings_window.settings.value("basic_auth", False, type=bool)
        username = (
            self.settings_window.settings.value("username", "", type=str)
            if basic_auth
            else ""
        )
        password = (
            self.settings_window.settings.value("password", "", type=str)
            if basic_auth
            else ""
        )

        # Run server.py in QProcess
        self.server_process = QProcess()
        self.server_process.setProgram(sys.executable)

        # pass config as environment vars to the server.py script
        env = QProcessEnvironment.systemEnvironment()
        env.insert("HOST", host)
        env.insert("PORT", str(port))
        env.insert("USERNAME", username)
        env.insert("PASSWORD", password)
        self.server_process.setProcessEnvironment(env)

        self.server_process.setWorkingDirectory(str(app_root()))
        if getattr(sys, "frozen", False):
            # A packaged build has no `-m` to fall back on; the frozen exe
            # relaunches itself and dispatches on this flag (see dashb/entry.py).
            self.server_process.setArguments(["--server"])
        else:
            # Run as a module from source so imports resolve the same way.
            self.server_process.setArguments(["-m", "dashb", "--server"])

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
            logger.warning("Server process killed")
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

    def _update_tray_icon(self):
        """Re-pick the tray icon variant after a live OS theme change."""
        icon = QIcon(str(_theme_icon_path()))
        self.tray_icon.setIcon(icon)
        self.setWindowIcon(icon)

    # close to tray
    def closeEvent(self, event):
        event.ignore()
        self.settings_window.hide()
        self.hide()

    def log_message(self, message: str):
        """Logs message to the text area."""
        logging.info(message)
        self.text_log.append(message)

    def on_open_themes_folder(self):
        """Open the writable user themes folder in the OS file browser, creating it first
        if this is the user's first time installing a theme.
        """
        theme_root = default_user_theme_root()
        theme_root.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(theme_root)))

    def on_install_theme(self):
        """Prompt for a theme zip, validate it, and install it into the user themes folder."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Install Theme", "", "Theme archive (*.zip)"
        )
        if not file_path:
            return

        theme_root = default_user_theme_root()
        try:
            theme_id = theme_id_in_zip(Path(file_path))
        except ThemeInstallError as ex:
            QMessageBox.critical(self, "Install Theme Failed", str(ex))
            return

        if theme_exists(theme_id, theme_root):
            answer = QMessageBox.question(
                self,
                "Theme Already Installed",
                f'A theme named "{theme_id}" is already installed. Overwrite it?',
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        try:
            theme = install_theme_from_zip(Path(file_path), theme_root)
        except ThemeInstallError as ex:
            QMessageBox.critical(self, "Install Theme Failed", str(ex))
            return

        QMessageBox.information(
            self,
            "Theme Installed",
            f'Installed "{theme.name}" ({theme.id}). It will show up next time the theme '
            "picker page is loaded.",
        )


class SettingsWindow(QMainWindow):
    def __init__(self):
        super(SettingsWindow, self).__init__()

        # Set window title and icon
        self.setWindowTitle("Settings")
        self.setWindowIcon(QIcon(str(_theme_icon_path())))

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
        if not startup.is_supported():
            self.run_on_startup.setEnabled(False)
            self.run_on_startup.setToolTip(
                "Run on startup is currently supported only on Windows."
            )

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
        try:
            startup.set_enabled(self.run_on_startup.isChecked())
        except (OSError, startup.StartupRegistrationError) as ex:
            QMessageBox.critical(
                self,
                "Startup Setting Failed",
                f"Dashb could not update the Windows startup setting:\n\n{ex}",
            )
            return

        self.settings.setValue("host", self.host_input.text())
        self.settings.setValue("port", self.port_input.text())
        self.settings.setValue("basic_auth", self.basic_auth.isChecked())
        self.settings.setValue("username", self.username_input.text())
        self.settings.setValue("password", self.password_input.text())
        # Older builds saved this flag but never registered a startup command.
        # The Windows Run key is now the source of truth.
        self.settings.remove("run_on_startup")
        self.close()

    def load_settings(self):
        """Load settings from persistent storage."""
        host = self.settings.value("host", "0.0.0.0", type=str)
        port = self.settings.value("port", "8080", type=str)
        basic_auth = self.settings.value("basic_auth", False, type=bool)
        username = self.settings.value("username", "", type=str)
        password = self.settings.value("password", "", type=str)
        legacy_run_on_startup = self.settings.value(
            "run_on_startup", False, type=bool
        )

        run_on_startup = startup.is_enabled()
        if startup.is_supported() and (run_on_startup or legacy_run_on_startup):
            try:
                # This both migrates the old no-op setting and refreshes an
                # existing registration if the portable exe has been moved.
                startup.set_enabled(True)
                run_on_startup = True
                self.settings.remove("run_on_startup")
            except OSError as ex:
                logger.warning("Could not refresh Dashb startup registration: %s", ex)

        self.host_input.setText(host)
        self.port_input.setText(port)
        self.basic_auth.setChecked(basic_auth)
        self.username_input.setText(username)
        self.password_input.setText(password)
        self.username_input.setEnabled(basic_auth)
        self.password_input.setEnabled(basic_auth)
        self.run_on_startup.setChecked(run_on_startup)


def _notify_running_instance() -> bool:
    """Ping the single-instance server; True if another instance is running."""
    socket = QLocalSocket()
    socket.connectToServer(SINGLE_INSTANCE_KEY)
    connected = socket.waitForConnected(500)
    if connected:
        socket.disconnectFromServer()
    return connected


def _claim_single_instance() -> QLocalServer | None:
    """Claim the app-wide lock before starting any server/helper processes."""
    server = QLocalServer()
    if server.listen(SINGLE_INSTANCE_KEY):
        return server

    if _notify_running_instance():
        return None

    # The name was occupied but could not be contacted, so it is safe to clean
    # up a stale Unix socket. This is a no-op for Windows named pipes.
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    server = QLocalServer()
    if server.listen(SINGLE_INSTANCE_KEY):
        return server

    # Close the remaining race where another launch claimed it after cleanup.
    if _notify_running_instance():
        return None
    raise RuntimeError(
        server.errorString() or "could not claim the single-instance lock"
    )


def _activate_window_for_later_launches(
    server: QLocalServer, window: "MainWindow"
) -> None:
    """Raise the existing window when a second Dashb launch pings it."""

    def _on_new_connection():
        connection = server.nextPendingConnection()
        if connection is not None:
            connection.disconnectFromServer()
            connection.deleteLater()
        window.show()
        window.raise_()
        window.activateWindow()

    server.newConnection.connect(_on_new_connection)
    # A second launch can connect in the short interval between claiming the
    # name and constructing MainWindow. Drain that already-queued activation.
    if server.hasPendingConnections():
        _on_new_connection()


def launch_application(args):
    app = QApplication()

    try:
        single_instance_server = _claim_single_instance()
    except RuntimeError as ex:
        QMessageBox.critical(None, "Dashb Could Not Start", str(ex))
        sys.exit(1)

    if single_instance_server is None:
        logger.warning("Dashb is already running; showing the existing window instead.")
        sys.exit(0)

    window = MainWindow()
    _activate_window_for_later_launches(single_instance_server, window)
    # Keep the listener alive for the app's lifetime by anchoring it to the window.
    window._single_instance_server = single_instance_server

    if startup.STARTUP_ARGUMENT not in args:
        window.show()
    app.exec()
    sys.exit()
