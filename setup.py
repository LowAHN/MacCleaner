from setuptools import setup

APP = ['mac_cleaner.py']
DATA_FILES = []

OPTIONS = {
    'argv_emulation': False,
    'iconfile': 'icon.icns',
    'plist': {
        'CFBundleName': 'MacCleaner',
        'CFBundleDisplayName': 'MacCleaner',
        'CFBundleIdentifier': 'com.maccleaner.app',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'LSMinimumSystemVersion': '12.0',
        'NSHumanReadableCopyright': 'MacCleaner - Open Source App Uninstaller',
        'NSHighResolutionCapable': True,
    },
    'packages': ['PyQt6'],
    'includes': [
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'plistlib',
        'shutil',
        'subprocess',
    ],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
