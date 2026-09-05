# Platform and Dependencies

## Deployment target

The primary target is Raspberry Pi 5 with 16 GB RAM, 64-bit Raspberry Pi OS
(`aarch64`), and Python 3.13.5. macOS is a development/test environment, not
proof of target compatibility. `setup.sh` is the owned installer and
`tests/test_setup_script.py` verifies its contract.

## Runtime layers

- Python packages are installed into `.venv`; `start_agent.sh` also accepts an
  existing `venv/`.
- PySide6-Essentials 6.11.1 supplies the Qt/QML production UI and has been
  validated on the target baseline.
- Whisper.cpp, Piper binaries/voices, and the wake-word model are project-local
  native/model artifacts, not Python-environment contents.
- Ollama and downloaded text/vision models are system services.
- `ffmpeg`/`ffplay` is a system package used by Music. Chromium is required
  only by the legacy Tk Weather fallback.
- `sshfs` and `fusermount3` are system commands used only by the optional
  iMessage Relay's manually authorized read-only phone mount. They are not
  installed in either Python virtual environment. `setup.sh` reports whether
  both commands already exist, asks `apt` to idempotently verify/install the
  `sshfs` package, and checks both commands afterward.
- Linux Python 3.13 uses OpenWakeWord 0.6 in ONNX-only mode; installer
  verification must instantiate the configured model, not merely import the
  package.

## Dependency changes

Before adding a dependency, establish upstream Python 3.13 and aarch64 support,
including wheel availability or a practical source build. Record its license,
version bounds, and the necessity/code-reduction/performance/runtime-cleanliness
justification. Update `requirements.txt`, `setup.sh`, docs, and installation
tests that own it. Do not infer compatibility from macOS success.

No new dependency should duplicate a small standard-library solution or create
an unsupported iPhone/Raspberry Pi deployment constraint. The iMessage parser,
state, and current receiver are intentionally standard-library-only.

The SSHFS client is OS-managed and deliberately unpinned so Raspberry Pi OS
can supply its patched repository revision. Debian publishes the 3.7.3 package
and FUSE 3 dependencies for `arm64`; upstream SSHFS is GPL-2.0. The physical
target validated SSHFS 3.7.3 with FUSE 3.17.2. This dependency keeps live Apple
data read-only and avoids phone-side project deployment; it adds no Python
package or import surface.

## Platform-owned resources

`setup.sh` validates Linux/aarch64, installs system packages, builds pinned
Whisper.cpp, downloads bounded artifacts, creates `.venv`, installs Python
requirements, pulls Ollama models, provisions wake-word assets, and performs
smoke checks. Local platform directories (`.venv/`, `piper/`, `whisper.cpp/`)
remain untracked.

Physical-device behavior that cannot be proved on macOS—camera commands,
Wayland/V3D rendering, touch/VNC, ALSA/PortAudio, joystick devices, rover LAN,
and long-running cleanup—must be recorded as unverified until target testing.
