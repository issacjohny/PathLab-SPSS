"""Append saved diagrams to SPSS's designated Viewer without touching data.

Image output uses IBM's documented SpssClient CreateImageChartItem and
InsertChildItem APIs. These calls must run after the statistical procedure has
ended, so the Viewer has received its tables before the diagrams are appended.
"""
from __future__ import annotations

import os
from pathlib import Path
import time


def _saved_locations(charts):
    folders = sorted({str(Path(chart["path"]).resolve().parent) for chart in charts if chart.get("path")})
    return "; ".join(folders)


def insert_charts(charts):
    """Insert chart files into the current output document; return any notices.

    The function never creates a new output document, changes the designated
    output document, submits analysis syntax, or reads/modifies the dataset.
    It does not delete chart files. SPSS embeds the pixels in saved SPV output;
    retaining the originals also lets researchers use the PNGs independently.
    """
    if not charts:
        return []
    saved = _saved_locations(charts)
    # IBM's bundled SpssClient wrapper uses these same context flags. An
    # external/headless Python call must not launch an interactive SPSS client.
    if os.environ.get("BACKEND_PYTHON_SCRIPT") != "True" and os.environ.get("FRONTEND_RUN_AUTO") != "True":
        return ["Diagrams were saved in %s. Embedded charts are available when PathLab runs from the SPSS menu." % saved]
    started = False
    notices = []
    try:
        import SpssClient
        SpssClient.StartClient()
        started = True
        doc = SpssClient.GetDesignatedOutputDoc()
        if doc is None:
            return ["SPSS has no designated Viewer document for the diagrams. The PNG files are saved in %s." % saved]
        # IBM documents asynchronous backend-to-Viewer rendering. This bounded
        # pause lets the just-finished procedure arrive before appending items.
        time.sleep(.2)
        items = doc.GetOutputItems()
        if items.Size() == 0:
            return ["The SPSS Viewer output is not ready for diagrams. The PNG files are saved in %s." % saved]
        root = items.GetItemAt(0).GetSpecificType()
        # Append to the existing root. SPSS 27 can invalidate a newly-created
        # header's ordinal position while procedure output is still arriving;
        # retrieving its specific type can also wait on the pending UI object.
        # Chart titles provide outline navigation without that fragile lookup.
        group = root
        for chart in charts:
            try:
                path = Path(chart["path"]).resolve()
                if not path.is_file():
                    raise FileNotFoundError("The rendered diagram file is no longer available: %s" % path)
                title = chart.get("title") or "PathLab diagram"
                image_item = doc.CreateImageChartItem(str(path), title)
                group.InsertChildItem(image_item, group.GetChildCount())
                note = chart.get("note")
                if note:
                    group.InsertChildItem(doc.CreateTextItem(str(note)), group.GetChildCount())
            except Exception as error:
                notices.append("SPSS could not insert %s in the Viewer (%s: %s). Its saved PNG is %s." %
                               (chart.get("title", "a diagram"), type(error).__name__, str(error), chart.get("path", saved)))
    except Exception as error:
        notices.append("SPSS could not attach the diagrams to the Viewer (%s: %s). The numerical results are complete; PNG files are saved in %s." %
                       (type(error).__name__, str(error), saved))
    finally:
        if started:
            try:
                SpssClient.StopClient()
            except Exception as error:
                notices.append("The Viewer connection could not be closed normally (%s: %s). Saved diagrams remain in %s." %
                               (type(error).__name__, str(error), saved))
    return notices
