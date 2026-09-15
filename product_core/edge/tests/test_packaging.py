from pathlib import Path

from app.version import APP_DISPLAY_NAME, APP_VERSION
from app.web_api import Api
from build_exe import (NAME, RELEASE_FOLDER, VERSION, _is_sensitive_release_path,
                       install_exe_runtime_config, restore_python_runtime_dlls,
                       verify_web_assets)


def test_release_filter_blocks_user_runtime_data():
    assert _is_sensitive_release_path(r"MSBRadarEdge\cauhinh.json")
    assert _is_sensitive_release_path(r"MSBRadarEdge\data\candidates.db")
    assert _is_sensitive_release_path(r"MSBRadarEdge\chrome_profile\Default\Cookies")


def test_release_filter_keeps_dependency_databases():
    assert not _is_sensitive_release_path(
        r"MSBRadarEdge\_internal\runtime\libreoffice\presets\database\biblio\biblio.dbf")
    assert not _is_sensitive_release_path(
        r"MSBRadarEdge\_internal\runtime\libreoffice\share\extensions\help.db_")


def test_runtime_config_is_installed_beside_exe(tmp_path):
    target = Path(install_exe_runtime_config(str(tmp_path)))
    assert target.name == f"{NAME}.exe.config"
    text = target.read_text(encoding="utf-8")
    assert "loadFromRemoteSources" in text


def test_main_does_not_create_a_secondary_dotnet_appdomain():
    source = Path(__file__).parents[1].joinpath("main.py").read_text(encoding="utf-8")
    assert "set_runtime(" not in source
    assert "get_netfx(" not in source


def test_release_version_has_one_source_of_truth():
    assert VERSION == APP_VERSION
    assert RELEASE_FOLDER == f"{NAME}_v{APP_VERSION}"
    assert APP_DISPLAY_NAME.endswith(f"v{APP_VERSION}")


def test_build_runs_the_packaged_startup_probe_before_release_zip():
    source = Path(__file__).parents[1].joinpath("build_exe.py").read_text(encoding="utf-8")
    assert source.index("restore_python_runtime_dlls(built_folder)") < source.index(
        "verify_packaged_startup(built_exe)")
    assert source.index("verify_packaged_startup(built_exe)") < source.index(
        "bo_qua = write_release_zip(built_folder")
    assert 'env["MSB_RADAR_RUNTIME_DIR"] = marker_dir' in source

    main_source = Path(__file__).parents[1].joinpath("main.py").read_text(encoding="utf-8")
    web_source = Path(__file__).parents[1].joinpath("app", "web", "app.js").read_text(encoding="utf-8")
    api_source = Path(__file__).parents[1].joinpath("app", "web_api.py").read_text(encoding="utf-8")
    assert "window.events.loaded.wait" in main_source
    assert "report_packaged_startup_ready(startupResults?.[4], initialDataReady)" in web_source
    assert "const initialDataReady = await this.loadInitialData()" in web_source
    assert "def report_packaged_startup_ready" in api_source


def test_packaged_startup_marker_requires_successful_runtime(tmp_path, monkeypatch):
    marker = tmp_path / "ready.txt"
    monkeypatch.setenv("MSB_RADAR_PACKAGED_STARTUP_PROBE", "1")
    monkeypatch.setenv("MSB_RADAR_PACKAGED_STARTUP_MARKER", str(marker))
    monkeypatch.setenv("MSB_RADAR_RUNTIME_DIR", str(tmp_path))
    api = Api.__new__(Api)

    failed = api.report_packaged_startup_ready({"ok": False}, True)
    assert failed["ok"] is False
    assert not marker.exists()

    assert api.report_packaged_startup_ready({"ok": True}, False)["ok"] is False
    passed = api.report_packaged_startup_ready({"ok": True}, True)
    assert passed == {"ok": True, "probe": True}
    assert marker.read_text(encoding="utf-8").startswith("JS bridge")


def test_restore_python_sqlite_dll_overwrites_foreign_runtime(tmp_path):
    internal = tmp_path / "_internal"
    internal.mkdir()
    target = internal / "sqlite3.dll"
    target.write_bytes(b"foreign LibreOffice sqlite")
    restored = restore_python_runtime_dlls(str(tmp_path))
    source = Path(__import__("sys").base_prefix) / "DLLs" / "sqlite3.dll"
    assert restored == [str(target)]
    assert target.read_bytes() == source.read_bytes()


def test_source_css_is_balanced_and_keeps_startup_layers():
    web_root = Path(__file__).parents[1] / "app" / "web"
    css = web_root.joinpath("styles.css").read_text(encoding="utf-8")
    assert css.count("{") == css.count("}")
    assert ".splash-overlay" in css
    assert ".modal-overlay" in css
    assert ".runtime-readiness-dialog" in css


def test_packaged_web_asset_validation(tmp_path):
    source_root = Path(__file__).parents[1] / "app" / "web"
    target_root = tmp_path / "_internal" / "app" / "web"
    target_root.mkdir(parents=True)
    for name in ("index.html", "styles.css", "app.js"):
        target_root.joinpath(name).write_bytes(source_root.joinpath(name).read_bytes())
    assert verify_web_assets(str(tmp_path)) is True

    target_root.joinpath("styles.css").write_text(".broken {", encoding="utf-8")
    try:
        verify_web_assets(str(tmp_path))
    except RuntimeError as exc:
        assert "không cân bằng ngoặc" in str(exc)
    else:
        raise AssertionError("CSS lỗi phải chặn phát hành")
