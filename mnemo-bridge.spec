# PyInstaller spec for the desktop app: pyinstaller mnemo-bridge.spec
#
# A folder build rather than one file, so Velopack updates only the files that
# changed. The output, dist/MnemoBridge/, is what `vpk pack --packDir`
# takes on Windows and Linux. On macOS it is also wrapped as
# dist/MnemoBridge.app. The icons come from tools/make_icons.py.

import sys

from PyInstaller.utils.hooks import collect_submodules

ICONS = {
    "win32": "assets/icon.ico",
    "darwin": "assets/icon.icns",
}

a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("mnemo_bridge/gui/web", "mnemo_bridge/gui/web"),
        # Linux window managers read the window icon from the running app.
        ("assets/icon.png", "assets"),
    ],
    # pywebview loads its backends lazily, velopack is reached through a star
    # import, and keyring finds its backends through entry points. Static
    # analysis misses all three.
    hiddenimports=(
        collect_submodules("webview")
        + collect_submodules("velopack")
        + collect_submodules("keyring.backends")
    ),
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MnemoBridge",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=ICONS.get(sys.platform),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="MnemoBridge",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="MnemoBridge.app",
        icon=ICONS["darwin"],
        bundle_identifier="one.mnemo.bridge",
        info_plist={
            "CFBundleDisplayName": "Mnemo Bridge",
            "CFBundleName": "Mnemo Bridge",
            "CFBundleShortVersionString": __import__("mnemo_bridge").__version__,
            "NSHighResolutionCapable": True,
        },
    )
