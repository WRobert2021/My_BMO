# Core Runtime

owner: `bmo.runtime.AssistantRuntime`

## Composition and startup

`agent.py` and `qt_agent.py` call `bmo.qt.app.run_qt_application`. QML loads
before `AssistantRuntime` constructs audio, wake-word, transcription, Ollama,
speech, archive, memory, feature, and mode services. `typed_agent.py` uses the
same production path with typed debug input; `tk_agent.py` is the explicit
legacy fallback.

`bmo.config.load_config()` overlays private user settings and extension wiring
onto in-memory defaults. Missing files are not created. `ToolRouter` loads the
feature registry; the runtime separately loads modes with a constrained
`ModeRuntimeContext`. `RuntimeExtensionCoordinator` owns both registries, the
live menu dispatcher, and worker queues for mode launches and feature vision
requests.

## Interaction flow

1. `RuntimeWorkerLoop` chooses queued menu work, quiet-hours pause, active-mode
   policy, typed input, push-to-talk, or wake-word input.
2. `RuntimeVoiceTurnExecutor` records into a new interaction archive,
   transcribes, records transcript events, and returns text to routing.
3. An active mode receives text first. Otherwise deterministic feature
   matchers run before local-model tool classification; unmatched requests are
   normal local-model conversation.
4. Tool results cross typed presentation/archive contracts. Generic image
   attachments and vision follow-ups do not require core knowledge of the
   producing plugin.
5. Speech is serialized through the runtime queue. Feature-view announcements
   use replaceable scopes and are blocked during Quiet Hours.

`bmo.runtime_loop`, `bmo.runtime_voice`, `bmo.runtime_menu`, and
`bmo.runtime_extensions` remain toolkit-neutral. Concrete audio, model, archive,
and presentation implementations are injected or composed by the runtime.

## Threads and resources

The runtime owns the assistant worker and speech worker. Audio stream cleanup
is cooperative with the creating thread. Intrinsic plugin workers remain owned
by their plugin and are reached only through registry lifecycle. The Qt event
thread owns controller/QML mutation; `QtRuntimePresentation` and `QtViewHost`
marshal worker callbacks through queued signals.

## Failure boundaries

Extension configuration/import/registration failures are isolated during
loading. A turn-level unexpected failure archives the failure when enabled,
presents a generic retry state, and leaves the worker loop usable. A failing
mode is released, closed, and quarantined. Startup can report a runtime error
without corrupting QML state.

## Shutdown

`bmo.qt.app` stops the Quiet Hours timer, then calls `AssistantRuntime.close()`,
the view host, and controller. The runtime marks exit, interrupts and wakes
waiters, closes the extension coordinator (feature registry then mode registry),
stops audio/speech activity, joins owned threads, saves bounded conversation
memory atomically, and unloads model state. One plugin cleanup failure is
reported without preventing remaining cleanup.

Primary tests: `tests/test_runtime_loop.py`, `tests/test_runtime_voice.py`,
`tests/test_runtime_extensions.py`, `tests/test_runtime_menu.py`,
`tests/test_interaction_failure_recovery.py`, and `tests/test_qt_shell.py`.
