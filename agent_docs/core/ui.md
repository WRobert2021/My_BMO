# Core UI Architecture

## Production boundary

PySide6/Qt Quick is the production presentation. `bmo.qt.app` creates
`QGuiApplication`, `QtFaceController`, `QtRuntimePresentation`, `QtViewHost`,
and `Main.qml`; the heavy runtime starts after QML loads. `tk_agent.py`,
`bmo.app`, and `bmo.ui.*` remain a temporary explicit fallback pending a
physical Raspberry Pi validation cycle.

The Qt event thread is the only owner of QML-visible state. Worker threads call
the toolkit-neutral presentation port; `QtRuntimePresentation` emits queued
signals. Hosted-view adapters may update only through `QtViewHost`, which owns
one active view, closes the previous view before replacement, routes action
signals, and dismisses back to the retained menu.

## Shared surfaces

`bmo/qt/qml/Main.qml` owns the 800x480 face, status/HUD, touch and keyboard
gestures, menu, attentions, quiet-hours cover, camera overlay, typed debug
input, and hosted-view surface. `HostedView.qml` selects plugin QML views from
the serialized `viewKind`/payload contract. Plugin-specific behavior and QML
belong to plugin docs.

`bmo.menu_model` owns 5x3 pagination, touch geometry, and swipe history.
`bmo.menu_catalog` namespaces feature/mode contributions and validates
selections. `bmo.menu_loader` reads configured metadata without constructing
tools, modes, stores, workers, clients, models, or UI. `bmo.runtime_menu`
validates selections against a current catalog; it does not branch on concrete
plugin names.

The shared compact face uses canonical upper-right bounds `x=684`, `y=5`,
108x65. `bmo.face_config` owns contained frame discovery/timing; production QML
uses the runtime controller's current frame. Legacy Tk views use
`bmo.ui.compact_face` and a visibility stack.

## Navigation and cleanup

A left swipe opens/advances the menu; a right swipe retraces pages and closes
from the first page. Menu selection retains the originating page underneath a
hosted view. Feature views open synchronously on the Qt thread; mode launch and
generic vision work are queued to the interaction worker. Closing a view must
cancel its scoped speech/timers, invalidate pending callbacks, release
plugin-owned resources, and return to the retained page.

Primary tests: `tests/test_qt_shell.py`, `tests/test_menu.py`,
`tests/test_menu_catalog.py`, `tests/test_compact_face.py`, and plugin-specific
Qt/view tests. Physical acceptance still covers cold start, touch/VNC, audio,
every enabled view/mode, cleanup, restart, and long-running stability; see the
opt-in migration history when that acceptance is the task.
