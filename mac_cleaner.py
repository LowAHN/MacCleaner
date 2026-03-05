#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MacCleaner - macOS Application Uninstaller
Scan installed apps, find related files, and cleanly remove them.
"""

import sys
import os
import shutil
import subprocess
import plistlib
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QLabel, QMessageBox,
    QProgressBar, QLineEdit, QTreeWidget, QTreeWidgetItem,
    QSplitter, QFrame, QHeaderView, QCheckBox, QGroupBox,
)
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QIcon, QPixmap, QFont, QColor, QPalette, QAction


# ─── App Scanner ──────────────────────────────────────

def get_app_icon(app_path):
    """앱 아이콘 추출"""
    try:
        info_plist = os.path.join(app_path, "Contents", "Info.plist")
        if os.path.exists(info_plist):
            with open(info_plist, "rb") as f:
                plist = plistlib.load(f)
            icon_name = plist.get("CFBundleIconFile", "")
            if icon_name:
                if not icon_name.endswith(".icns"):
                    icon_name += ".icns"
                icon_path = os.path.join(app_path, "Contents", "Resources", icon_name)
                if os.path.exists(icon_path):
                    return icon_path
    except Exception:
        pass
    return None


def get_app_info(app_path):
    """앱 정보 추출"""
    info = {
        "name": os.path.basename(app_path).replace(".app", ""),
        "path": app_path,
        "bundle_id": "",
        "version": "",
        "size": 0,
        "icon_path": None,
    }

    try:
        info_plist = os.path.join(app_path, "Contents", "Info.plist")
        if os.path.exists(info_plist):
            with open(info_plist, "rb") as f:
                plist = plistlib.load(f)
            info["bundle_id"] = plist.get("CFBundleIdentifier", "")
            info["version"] = plist.get("CFBundleShortVersionString", "")
    except Exception:
        pass

    info["icon_path"] = get_app_icon(app_path)

    try:
        result = subprocess.run(
            ["du", "-sk", app_path],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            info["size"] = int(result.stdout.split()[0]) * 1024
    except Exception:
        pass

    return info


def format_size(size_bytes):
    """바이트를 읽기 좋은 형식으로"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / 1024**2:.1f} MB"
    return f"{size_bytes / 1024**3:.2f} GB"


def find_related_files(app_info):
    """앱 관련 파일/폴더 찾기"""
    related = []
    home = Path.home()
    bundle_id = app_info["bundle_id"]
    app_name = app_info["name"]

    search_dirs = {
        "Preferences": home / "Library" / "Preferences",
        "Application Support": home / "Library" / "Application Support",
        "Caches": home / "Library" / "Caches",
        "Logs": home / "Library" / "Logs",
        "Containers": home / "Library" / "Containers",
        "Group Containers": home / "Library" / "Group Containers",
        "Saved Application State": home / "Library" / "Saved Application State",
        "WebKit": home / "Library" / "WebKit",
        "HTTPStorages": home / "Library" / "HTTPStorages",
        "Cookies": home / "Library" / "Cookies",
    }

    for category, search_dir in search_dirs.items():
        if not search_dir.exists():
            continue
        try:
            for item in search_dir.iterdir():
                name_lower = item.name.lower()
                match = False

                if bundle_id and bundle_id.lower() in name_lower:
                    match = True
                elif app_name.lower() in name_lower:
                    match = True

                if match:
                    size = 0
                    try:
                        if item.is_file():
                            size = item.stat().st_size
                        elif item.is_dir():
                            result = subprocess.run(
                                ["du", "-sk", str(item)],
                                capture_output=True, text=True, timeout=5
                            )
                            if result.returncode == 0:
                                size = int(result.stdout.split()[0]) * 1024
                    except Exception:
                        pass

                    related.append({
                        "path": str(item),
                        "category": category,
                        "size": size,
                        "name": item.name,
                    })
        except PermissionError:
            pass

    return related


# ─── Worker Thread ────────────────────────────────────

class ScanWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)

    def __init__(self, scan_dirs=None):
        super().__init__()
        self.scan_dirs = scan_dirs or ["/Applications"]

    def run(self):
        apps = []
        all_items = []
        for scan_dir in self.scan_dirs:
            if os.path.exists(scan_dir):
                items = [
                    os.path.join(scan_dir, f)
                    for f in os.listdir(scan_dir)
                    if f.endswith(".app")
                ]
                all_items.extend(items)

        total = len(all_items)
        for i, app_path in enumerate(all_items):
            name = os.path.basename(app_path).replace(".app", "")
            self.progress.emit(i + 1, total, name)
            info = get_app_info(app_path)
            apps.append(info)

        apps.sort(key=lambda x: x["name"].lower())
        self.finished.emit(apps)


class DeleteWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, app_path, related_paths):
        super().__init__()
        self.app_path = app_path
        self.related_paths = related_paths

    def run(self):
        errors = []

        # 관련 파일 먼저 삭제
        for path in self.related_paths:
            try:
                self.progress.emit(f"Removing: {os.path.basename(path)}")
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
            except Exception as e:
                errors.append(f"{path}: {e}")

        # 앱 삭제
        try:
            self.progress.emit(f"Removing: {os.path.basename(self.app_path)}")
            # 먼저 일반 삭제 시도
            shutil.rmtree(self.app_path)
        except PermissionError:
            # 권한 필요 시 osascript 사용
            try:
                script = f'do shell script "rm -rf \'{self.app_path}\'" with administrator privileges'
                subprocess.run(
                    ["osascript", "-e", script],
                    capture_output=True, timeout=30
                )
            except Exception as e:
                errors.append(f"App: {e}")

        if errors:
            self.finished.emit(False, "\n".join(errors))
        else:
            self.finished.emit(True, "")


# ─── Main Window ──────────────────────────────────────

STYLE = """
QMainWindow {
    background-color: #1a1a2e;
}
QWidget {
    background-color: #1a1a2e;
    color: #e0e0e0;
    font-family: -apple-system, 'SF Pro Display', 'Helvetica Neue';
}
QListWidget {
    background-color: #16213e;
    border: 1px solid #2a2a4a;
    border-radius: 8px;
    padding: 4px;
    font-size: 13px;
}
QListWidget::item {
    padding: 8px 12px;
    border-radius: 6px;
    margin: 2px 4px;
}
QListWidget::item:selected {
    background-color: #0f3460;
    color: #e94560;
}
QListWidget::item:hover {
    background-color: #1a3a5c;
}
QTreeWidget {
    background-color: #16213e;
    border: 1px solid #2a2a4a;
    border-radius: 8px;
    padding: 4px;
    font-size: 12px;
}
QTreeWidget::item {
    padding: 6px 4px;
}
QTreeWidget::item:selected {
    background-color: #0f3460;
}
QHeaderView::section {
    background-color: #16213e;
    color: #8888aa;
    border: none;
    padding: 8px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton {
    border: 1px solid #2a2a4a;
    border-radius: 8px;
    padding: 10px 20px;
    font-size: 13px;
    font-weight: 600;
    background-color: #16213e;
    color: #e0e0e0;
}
QPushButton:hover {
    background-color: #1a3a5c;
    border-color: #5b8def;
}
QPushButton#deleteBtn {
    background-color: #e94560;
    border-color: #e94560;
    color: white;
}
QPushButton#deleteBtn:hover {
    background-color: #ff6b81;
}
QPushButton#deleteBtn:disabled {
    background-color: #4a2030;
    border-color: #4a2030;
    color: #888;
}
QLineEdit {
    background-color: #16213e;
    border: 1px solid #2a2a4a;
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 13px;
    color: #e0e0e0;
}
QLineEdit:focus {
    border-color: #5b8def;
}
QProgressBar {
    background-color: #16213e;
    border: 1px solid #2a2a4a;
    border-radius: 6px;
    height: 6px;
    text-align: center;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #5b8def, stop:1 #a78bfa);
    border-radius: 4px;
}
QLabel#titleLabel {
    font-size: 22px;
    font-weight: 700;
    color: #e94560;
}
QLabel#subtitleLabel {
    font-size: 12px;
    color: #8888aa;
}
QLabel#infoLabel {
    font-size: 13px;
    color: #aaaacc;
    padding: 8px;
}
QLabel#sizeLabel {
    font-size: 15px;
    font-weight: 700;
    color: #e94560;
}
QFrame#separator {
    background-color: #2a2a4a;
    max-height: 1px;
}
QGroupBox {
    border: 1px solid #2a2a4a;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 20px;
    font-size: 13px;
    font-weight: 600;
    color: #8888aa;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
QCheckBox {
    font-size: 12px;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #2a2a4a;
    background-color: #16213e;
}
QCheckBox::indicator:checked {
    background-color: #5b8def;
    border-color: #5b8def;
}
"""


class MacCleanerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.apps = []
        self.current_app = None
        self.related_files = []
        self.init_ui()
        self.scan_apps()

    def init_ui(self):
        self.setWindowTitle("MacCleaner")
        self.setMinimumSize(1000, 650)
        self.resize(1100, 700)
        self.setStyleSheet(STYLE)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(16, 12, 16, 12)
        main_layout.setSpacing(12)

        # ── Header ──
        header = QHBoxLayout()
        title_area = QVBoxLayout()
        title = QLabel("MacCleaner")
        title.setObjectName("titleLabel")
        subtitle = QLabel("Installed applications and related files manager")
        subtitle.setObjectName("subtitleLabel")
        title_area.addWidget(title)
        title_area.addWidget(subtitle)
        header.addLayout(title_area)
        header.addStretch()

        self.scan_btn = QPushButton("Rescan")
        self.scan_btn.clicked.connect(self.scan_apps)
        header.addWidget(self.scan_btn)

        main_layout.addLayout(header)

        # ── Search ──
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search applications...")
        self.search_input.textChanged.connect(self.filter_apps)
        main_layout.addWidget(self.search_input)

        # ── Content area ──
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: App list
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.app_count_label = QLabel("Applications: scanning...")
        self.app_count_label.setObjectName("subtitleLabel")
        left_layout.addWidget(self.app_count_label)

        self.app_list = QListWidget()
        self.app_list.setIconSize(QSize(32, 32))
        self.app_list.currentItemChanged.connect(self.on_app_selected)
        left_layout.addWidget(self.app_list)

        splitter.addWidget(left_widget)

        # Right: Details
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # App info
        info_group = QGroupBox("Application Info")
        info_layout = QVBoxLayout(info_group)

        self.info_name = QLabel("Select an application")
        self.info_name.setFont(QFont("", 16, QFont.Weight.Bold))
        info_layout.addWidget(self.info_name)

        self.info_details = QLabel("")
        self.info_details.setObjectName("infoLabel")
        self.info_details.setWordWrap(True)
        info_layout.addWidget(self.info_details)

        right_layout.addWidget(info_group)

        # Related files
        files_group = QGroupBox("Related Files")
        files_layout = QVBoxLayout(files_group)

        self.select_all_cb = QCheckBox("Select All")
        self.select_all_cb.setChecked(True)
        self.select_all_cb.stateChanged.connect(self.toggle_select_all)
        files_layout.addWidget(self.select_all_cb)

        self.files_tree = QTreeWidget()
        self.files_tree.setHeaderLabels(["Name", "Category", "Size"])
        self.files_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.files_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.files_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.files_tree.setColumnWidth(1, 150)
        self.files_tree.setColumnWidth(2, 80)
        files_layout.addWidget(self.files_tree)

        right_layout.addWidget(files_group)

        # Total size + Delete
        bottom_bar = QHBoxLayout()
        self.total_size_label = QLabel("")
        self.total_size_label.setObjectName("sizeLabel")
        bottom_bar.addWidget(self.total_size_label)
        bottom_bar.addStretch()

        self.delete_btn = QPushButton("Uninstall")
        self.delete_btn.setObjectName("deleteBtn")
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self.delete_app)
        bottom_bar.addWidget(self.delete_btn)

        right_layout.addLayout(bottom_bar)

        splitter.addWidget(right_widget)
        splitter.setSizes([350, 650])

        main_layout.addWidget(splitter)

        # ── Status bar ──
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setTextVisible(False)
        main_layout.addWidget(self.progress)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("subtitleLabel")
        main_layout.addWidget(self.status_label)

    def scan_apps(self):
        self.app_list.clear()
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.scan_btn.setEnabled(False)
        self.status_label.setText("Scanning applications...")

        user_apps = os.path.expanduser("~/Applications")
        scan_dirs = ["/Applications"]
        if os.path.exists(user_apps):
            scan_dirs.append(user_apps)

        self.worker = ScanWorker(scan_dirs)
        self.worker.progress.connect(self.on_scan_progress)
        self.worker.finished.connect(self.on_scan_finished)
        self.worker.start()

    def on_scan_progress(self, current, total, name):
        self.progress.setRange(0, total)
        self.progress.setValue(current)
        self.status_label.setText(f"Scanning: {name}")

    def on_scan_finished(self, apps):
        self.apps = apps
        self.progress.setVisible(False)
        self.scan_btn.setEnabled(True)
        self.app_count_label.setText(f"Applications: {len(apps)}")
        self.status_label.setText(f"Found {len(apps)} applications")
        self.populate_app_list(apps)

    def populate_app_list(self, apps):
        self.app_list.clear()
        for app in apps:
            item = QListWidgetItem()
            size_str = format_size(app["size"])
            item.setText(f"{app['name']}  ({size_str})")
            item.setData(Qt.ItemDataRole.UserRole, app)

            if app["icon_path"]:
                pixmap = QPixmap(app["icon_path"])
                if not pixmap.isNull():
                    item.setIcon(QIcon(pixmap.scaled(
                        32, 32,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )))

            self.app_list.addItem(item)

    def filter_apps(self, text):
        text = text.lower()
        filtered = [a for a in self.apps if text in a["name"].lower()]
        self.populate_app_list(filtered)
        self.app_count_label.setText(f"Applications: {len(filtered)}")

    def on_app_selected(self, current, previous):
        if not current:
            return

        app = current.data(Qt.ItemDataRole.UserRole)
        self.current_app = app

        self.info_name.setText(app["name"])
        details = []
        if app["version"]:
            details.append(f"Version: {app['version']}")
        if app["bundle_id"]:
            details.append(f"Bundle ID: {app['bundle_id']}")
        details.append(f"Size: {format_size(app['size'])}")
        details.append(f"Location: {app['path']}")
        self.info_details.setText("\n".join(details))

        # Find related files
        self.status_label.setText(f"Searching related files for {app['name']}...")
        QApplication.processEvents()

        self.related_files = find_related_files(app)
        self.files_tree.clear()

        total_related_size = 0
        for rf in self.related_files:
            item = QTreeWidgetItem()
            item.setText(0, rf["name"])
            item.setText(1, rf["category"])
            item.setText(2, format_size(rf["size"]))
            item.setCheckState(0, Qt.CheckState.Checked)
            item.setData(0, Qt.ItemDataRole.UserRole, rf["path"])
            self.files_tree.addTopLevelItem(item)
            total_related_size += rf["size"]

        total_size = app["size"] + total_related_size
        self.total_size_label.setText(
            f"Total: {format_size(total_size)}  "
            f"(App: {format_size(app['size'])} + Related: {format_size(total_related_size)})"
        )

        self.delete_btn.setEnabled(True)
        self.select_all_cb.setChecked(True)
        self.status_label.setText(
            f"Found {len(self.related_files)} related items for {app['name']}"
        )

    def toggle_select_all(self, state):
        check = Qt.CheckState.Checked if state == 2 else Qt.CheckState.Unchecked
        for i in range(self.files_tree.topLevelItemCount()):
            self.files_tree.topLevelItem(i).setCheckState(0, check)

    def delete_app(self):
        if not self.current_app:
            return

        app_name = self.current_app["name"]

        # Collect checked related files
        selected_paths = []
        for i in range(self.files_tree.topLevelItemCount()):
            item = self.files_tree.topLevelItem(i)
            if item.checkState(0) == Qt.CheckState.Checked:
                selected_paths.append(item.data(0, Qt.ItemDataRole.UserRole))

        # Confirmation
        msg = QMessageBox(self)
        msg.setWindowTitle("Confirm Uninstall")
        msg.setText(f"Are you sure you want to uninstall '{app_name}'?")
        msg.setInformativeText(
            f"This will remove the application and {len(selected_paths)} related item(s).\n"
            "This action cannot be undone."
        )
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        msg.setDefaultButton(QMessageBox.StandardButton.Cancel)
        msg.setIcon(QMessageBox.Icon.Warning)

        if msg.exec() != QMessageBox.StandardButton.Yes:
            return

        self.delete_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)

        self.del_worker = DeleteWorker(self.current_app["path"], selected_paths)
        self.del_worker.progress.connect(lambda s: self.status_label.setText(s))
        self.del_worker.finished.connect(self.on_delete_finished)
        self.del_worker.start()

    def on_delete_finished(self, success, error_msg):
        self.progress.setVisible(False)

        if success:
            QMessageBox.information(
                self, "Complete",
                f"'{self.current_app['name']}' has been successfully uninstalled."
            )
            self.current_app = None
            self.scan_apps()
        else:
            QMessageBox.warning(
                self, "Partial Error",
                f"Some items could not be removed:\n\n{error_msg}"
            )
            self.scan_apps()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("MacCleaner")
    app.setApplicationDisplayName("MacCleaner")

    window = MacCleanerApp()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
