from pathlib import Path


SPEC_DIR = Path(SPECPATH).resolve(strict=True)
ENTRYPOINT = SPEC_DIR / "managed_frozen_operational_entrypoint.py"

# The nine verified operational modules remain external bundle data. They are
# loaded from the outer app's Resources/ManagedOperationalRuntime by the
# entrypoint and are intentionally absent from Analysis/PYZ here.
a = Analysis(
    [str(ENTRYPOINT)],
    pathex=[str(SPEC_DIR)],
    binaries=[],
    datas=[],
    hiddenimports=["frozen_runtime_imports"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="UPSOperationalHelper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    target_arch="arm64",
    codesign_identity=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="UPSOperationalHelper",
)
app = BUNDLE(
    coll,
    name="UPSOperationalHelper.app",
    icon=None,
    bundle_identifier="org.upsmonitor.synthetic.operational-helper",
    version="0.1.0",
    info_plist={"LSUIElement": True},
)
