import sys
import asyncio
import logging
import threading
from PyQt6.QtWidgets import QMainWindow, QSystemTrayIcon, QMenu, QApplication, QTextEdit, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QFrame, QWidget, QCheckBox, QLineEdit, QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import QSettings
from aiohttp import web
import asyncio


class MainWindow(QMainWindow):
    def __init__(self):
        super(MainWindow, self).__init__()

        # set window title and icon
        self.setWindowTitle("Gayj")
        self.setWindowIcon(QIcon("icon.svg"))

        # Create a tray icon
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon("icon.svg"))
        self.tray_icon.setToolTip("Gayj")
        self.tray_icon.show()

        # tray menu
        self.tray_menu = QMenu()
        self.tray_icon.setContextMenu(self.tray_menu)
        quit_action = self.tray_menu.addAction("Quit")
        quit_action.triggered.connect(QApplication.quit)
        # click tray icon to show window
        self.tray_icon.activated.connect(lambda reason: reason == QSystemTrayIcon.ActivationReason.Trigger and self.show())

        # Initialize the logger for server log output
        self.logger = logging.getLogger('server')
        self.logger.setLevel(logging.INFO)
        self.log_handler = QtLogHandler(self)
        self.logger.addHandler(self.log_handler)

        # Create a button for starting and stopping the server
        self.button_start_stop = QPushButton("Start Server", self)
        self.button_start_stop.clicked.connect(self.start_stop_server)

        # Create a button for opening settings
        self.button_settings = QPushButton("Settings", self)
        self.button_settings.clicked.connect(lambda: self.settings_window.show())
        self.settings_window = SettingsWindow()

        # Create a read-only text for showing server log
        self.text_log = QTextEdit(self)
        self.text_log.setReadOnly(True)

        # Create the layout for buttons
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.button_start_stop)
        button_layout.addStretch()  # Spacer to push button to the right
        button_layout.addWidget(self.button_settings)

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

        # Initialize server state
        self.server_running = False
        self.server_thread = None

    # close to tray
    def closeEvent(self, event):
        event.ignore()
        self.settings_window.hide()
        self.hide()

    def log_message(self, message):
        """Logs message to the text area."""
        self.text_log.append(message)

    def start_stop_server(self):
        if self.server_running: 
            self.stop_server()
        else:
            self.start_server()

    def start_server(self):
        """Starts the HTTP/WebSocket server in a separate thread."""
        self.logger.info("Starting server")
        self.server_running = True
        self.button_start_stop.setText("Stop Server")

        # Initialize the server class and pass the logger
        self.server = MyServer(logger=self.logger)

        # Run the server in a separate thread
        self.server_thread = threading.Thread(target=self.run_server_in_thread, daemon=True)
        self.server_thread.start()

    def stop_server(self):
        """Stops the HTTP/WebSocket server."""
        self.logger.info("Stopping server")
        self.server_running = False
        self.button_start_stop.setText("Start Server")

    def run_server_in_thread(self):
        """Runs the server in a separate thread."""
        asyncio.run(self.server.start())


class MyServer:
    def __init__(self, logger=None):
        """Initialize the server with the logger from the main window."""
        self.logger = logger
        self.app = web.Application()

        # Set up routes
        self.app.router.add_get('/', self.http_handler)
        self.app.router.add_get('/ws', self.websocket_handler)

    async def start(self):
        """Starts the aiohttp server."""
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, 'localhost', 8080)
        self.logger.info("Server started at http://localhost:8080")
        await site.start()

        # Keep the server running
        while True:
            await asyncio.sleep(1)

    async def http_handler(self, request):
        """Handle HTTP requests at /."""
        self.logger.info("Received HTTP request")
        return web.Response(text="Hello from HTTP server!")

    async def websocket_handler(self, request):
        """Handle WebSocket connections at /ws."""
        self.logger.info("WebSocket connection established")
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                await ws.send_str(f"Server received: {msg.data}")
                self.logger.info(f"Received WebSocket message: {msg.data}")
            elif msg.type == web.WSMsgType.CLOSE:
                break

        self.logger.info("WebSocket connection closed")
        return ws

class SettingsWindow(QMainWindow):
    def __init__(self):
        super(SettingsWindow, self).__init__()

        # Set window title and icon
        self.setWindowTitle("Settings")
        self.setWindowIcon(QIcon("icon.svg"))

        # Initialize QSettings
        self.settings = QSettings("MyApp", "GayjApp")

        # Create a QLineEdit with label for server port
        self.port_label = QLabel("Port:", self)
        self.port_input = QLineEdit(self)
        self.port_input.setFixedWidth(50)

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
        """ Save settings to persistent storage. """
        self.settings.setValue("port", self.port_input.text())
        self.settings.setValue("run_on_startup", self.run_on_startup.isChecked())
        self.close()

    def load_settings(self):
        """ Load settings from persistent storage. """
        port = self.settings.value("port", "")
        run_on_startup = self.settings.value("run_on_startup", False, type=bool)

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
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
