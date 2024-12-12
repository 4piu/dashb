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
    QFrame,
    QWidget,
    QCheckBox,
    QLineEdit,
    QSystemTrayIcon,
    QMenu,
)
from PySide6.QtGui import QIcon, QIntValidator, QRegularExpressionValidator
from PySide6.QtCore import QSettings, QRegularExpression

from server import WebServer

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class MainWindow(QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()

        # Initialize the logger
        logger_handler = QtLogHandler(self)
        logger_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
        logger.addHandler(logger_handler)

        # HTTP and WebSocket servers
        self.server = WebServer(logger)

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

        # Create a button for restarting the server
        self.btn_restart_server = QPushButton("Restart Server", self)
        self.btn_restart_server.clicked.connect(self.restart_server)

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
        button_layout.addWidget(self.btn_restart_server)
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
        host = self.settings_window.settings.value("host", "0.0.0.0", type=str)
        port = self.settings_window.settings.value("port", 8080, type=int)
        try:
            self.server.start(host, port)
        except Exception as e:
            logger.error(f"Error starting server: {e}")

    def restart_server(self):
        """Restart the server."""
        host = self.settings_window.settings.value("host", "0.0.0.0", type=str)
        port = self.settings_window.settings.value("port", 8080, type=int)
        self.server.stop()
        self.server.start(host, port)

    # close to tray
    def closeEvent(self, event):
        event.ignore()
        self.settings_window.hide()
        self.hide()

    def log_message(self, message):
        """Logs message to the text area."""
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
        self.port_input.setValidator(QIntValidator(1,65535)) # 1-65535 numbers only

        # Create a check box for run on startup
        self.run_on_startup = QCheckBox("Run on startup", self)

        # Create a button for canceling settings
        self.button_cancel = QPushButton("Cancel", self)
        self.button_cancel.clicked.connect(self.close)

        # Create a button for saving settings
        self.button_save = QPushButton("Save", self)
        self.button_save.clicked.connect(self.save_settings)

        # Create the form layout for the label and input
        form_layout = QHBoxLayout()
        form_layout.addWidget(self.host_label)
        form_layout.addWidget(self.host_input)
        form_layout.addWidget(self.port_label)
        form_layout.addWidget(self.port_input)

        # Create the layout for buttons (Save and Cancel)
        button_layout = QHBoxLayout()
        button_layout.addStretch()  # Add spacer to push buttons to the right
        button_layout.addWidget(self.button_cancel)
        button_layout.addWidget(self.button_save)

        # Main layout
        main_layout = QVBoxLayout()
        main_layout.addLayout(form_layout)  # Add the form (label + input)
        main_layout.addWidget(self.run_on_startup)  # Add the checkbox
        main_layout.addStretch()  # Add spacer to push buttons to the bottom
        main_layout.addLayout(button_layout)  # Add the button layout

        # Set the layout to the central widget
        central_widget = QWidget(self)
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

        # Load saved settings
        self.load_settings()

    def save_settings(self):
        """Save settings to persistent storage."""
        self.settings.setValue("host", self.host_input.text())
        self.settings.setValue("port", self.port_input.text())
        self.settings.setValue("run_on_startup", self.run_on_startup.isChecked())
        self.close()

    def load_settings(self):
        """Load settings from persistent storage."""
        host = self.settings.value("host", "0.0.0.0", type=str)
        port = self.settings.value("port", "8080", type=str)
        run_on_startup = self.settings.value("run_on_startup", False, type=bool)

        self.host_input.setText(host)
        self.port_input.setText(port)
        self.run_on_startup.setChecked(run_on_startup)


class QtLogHandler(logging.Handler):
    """Custom log handler to redirect log messages to the QTextEdit widget."""

    def __init__(self, window):
        super().__init__()
        self.window = window

    def emit(self, record):
        log_entry = self.format(record)
        self.window.log_message(log_entry)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.exec()
    sys.exit()


if __name__ == "__main__":
    main()
