"""Native image insertion preserves data and the designated output document."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pathlab_spss import viewer


class Header:
    def __init__(self):
        self.children = []

    def InsertChildItem(self, item, index):
        self.children.insert(index, item)

    def GetChildCount(self):
        return len(self.children)

    def GetChildItem(self, index):
        return self.children[index]


class Item:
    def __init__(self, kind, value, specific=None):
        self.kind, self.value, self.specific = kind, value, specific

    def GetSpecificType(self):
        return self.specific


@pytest.fixture
def native_viewer(monkeypatch):
    monkeypatch.setenv("BACKEND_PYTHON_SCRIPT", "True")
    monkeypatch.delenv("FRONTEND_RUN_AUTO", raising=False)
    monkeypatch.setattr(viewer.time, "sleep", lambda seconds: None)
    root = Header()
    root.children.append(Item("existing", "Existing user output"))
    state = {"started": 0, "stopped": 0, "images": [], "root": root, "designated": None}

    class Document:
        def GetOutputItems(self):
            return SimpleNamespace(Size=lambda: 1, GetItemAt=lambda index: Item("root", "Output", root))

        def CreateHeaderItem(self, title):
            return Item("header", title, Header())

        def CreateImageChartItem(self, path, title):
            state["images"].append((path, title))
            return Item("chart", title)

        def CreateTextItem(self, text):
            return Item("text", text)

    state["designated"] = Document()
    fake = SimpleNamespace(
        StartClient=lambda: state.update(started=state["started"] + 1),
        StopClient=lambda: state.update(stopped=state["stopped"] + 1),
        GetDesignatedOutputDoc=lambda: state["designated"],
    )
    monkeypatch.setitem(sys.modules, "SpssClient", fake)
    return state


def test_charts_append_without_changing_existing_output(native_viewer, tmp_path):
    image = tmp_path / "interaction.png"
    image.write_bytes(b"synthetic image stub")
    original = native_viewer["root"].children[0]
    doc = native_viewer["designated"]
    notices = viewer.insert_charts([{"path": str(image), "title": "Interaction: X to Y", "note": "Pointwise intervals."}])
    assert notices == []
    assert native_viewer["root"].children[0] is original
    assert [child.kind for child in native_viewer["root"].children] == ["existing", "chart", "text"]
    assert native_viewer["designated"] is doc
    assert native_viewer["started"] == native_viewer["stopped"] == 1
    assert image.is_file(), "Researcher PNG export must not be deleted after insertion"


def test_async_root_positions_are_not_used_to_find_new_chart_group(native_viewer, tmp_path):
    image = tmp_path / "jn.png"
    image.write_bytes(b"synthetic image stub")
    def stale_position(index):
        raise RuntimeError("Root child positions changed while procedure output arrived")
    native_viewer["root"].GetChildItem = stale_position
    assert viewer.insert_charts([{"path": str(image), "title": "Johnson–Neyman"}]) == []
    assert native_viewer["images"] == [(str(image), "Johnson–Neyman")]


def test_headless_mode_keeps_saved_images_without_starting_client(native_viewer, monkeypatch, tmp_path):
    monkeypatch.delenv("BACKEND_PYTHON_SCRIPT")
    path = tmp_path / "jn.png"
    notices = viewer.insert_charts([{"path": str(path), "title": "Johnson–Neyman"}])
    assert "SPSS menu" in notices[0] and str(tmp_path) in notices[0]
    assert native_viewer["started"] == native_viewer["stopped"] == 0


def test_no_output_document_returns_file_location_and_closes_connection(native_viewer, tmp_path):
    native_viewer["designated"] = None
    notices = viewer.insert_charts([{"path": str(tmp_path / "jn.png")}])
    assert "no designated Viewer" in notices[0]
    assert native_viewer["started"] == native_viewer["stopped"] == 1


def test_one_missing_image_does_not_discard_other_diagrams(native_viewer, tmp_path):
    good = tmp_path / "good.png"
    good.write_bytes(b"synthetic")
    notices = viewer.insert_charts([{"path": str(tmp_path / "missing.png"), "title": "Unavailable chart"},
                                   {"path": str(good), "title": "Available chart"}])
    assert len(notices) == 1 and "FileNotFoundError" in notices[0]
    assert native_viewer["images"] == [(str(good), "Available chart")]
    assert native_viewer["stopped"] == 1


def test_no_charts_does_not_open_a_client(native_viewer):
    assert viewer.insert_charts([]) == []
    assert native_viewer["started"] == 0
