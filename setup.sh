#!/bin/bash
set -Eeuo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$BASE_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

WHISPER_CPP_VERSION="${WHISPER_CPP_VERSION:-v1.9.2}"
WHISPER_BINARY_RELATIVE="whisper.cpp/build/bin/whisper-cli"
WHISPER_MODEL_RELATIVE="whisper.cpp/models/ggml-base.en.bin"
WHISPER_DIR="$BASE_DIR/whisper.cpp"
WHISPER_BINARY="$BASE_DIR/$WHISPER_BINARY_RELATIVE"
WHISPER_MODEL="$BASE_DIR/$WHISPER_MODEL_RELATIVE"
WHISPER_MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"

PIPER_VERSION="2023.11.14-2"
PIPER_DIR="$BASE_DIR/piper"
PIPER_BINARY="$PIPER_DIR/piper"
PIPER_VOICE="$PIPER_DIR/en_GB-semaine-medium.onnx"
PIPER_VOICE_CONFIG="$PIPER_VOICE.json"

BMO_VOICE_RELEASE="v1.0-voice"
BMO_VOICE="$BASE_DIR/voices/bmo.onnx"
BMO_VOICE_CONFIG="$BMO_VOICE.json"

VENV_DIR="$BASE_DIR/venv"
VENV_PYTHON="$VENV_DIR/bin/python"
WAKE_WORD_MODEL="$BASE_DIR/wakeword.onnx"

TEXT_MODEL="gemma3:1b"
VISION_MODEL="moondream"

handle_error() {
    local status=$?
    local line="${BASH_LINENO[0]:-unknown}"
    echo -e "${RED}❌ Setup failed near line ${line} (exit ${status}).${NC}" >&2
    exit "$status"
}

require_command() {
    local command_name=$1
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo -e "${RED}❌ Required command not found: ${command_name}${NC}" >&2
        return 1
    fi
}

file_size() {
    wc -c < "$1" | tr -d '[:space:]'
}

download_file() {
    local url=$1
    local destination=$2
    local minimum_size=$3
    local description=$4
    local current_size=0
    local downloaded_size
    local temporary_file

    if [ -f "$destination" ]; then
        current_size="$(file_size "$destination")"
    fi
    if [ "$current_size" -ge "$minimum_size" ]; then
        echo -e "${GREEN}${description} is already present.${NC}"
        return 0
    fi

    temporary_file="$(mktemp "${destination}.part.XXXXXX")"
    if ! curl --fail --location --show-error --silent \
        --retry 3 --retry-delay 2 --connect-timeout 20 \
        --output "$temporary_file" "$url"; then
        rm -f "$temporary_file"
        echo -e "${RED}❌ Failed to download ${description}.${NC}" >&2
        return 1
    fi

    downloaded_size="$(file_size "$temporary_file")"
    if [ "$downloaded_size" -lt "$minimum_size" ]; then
        rm -f "$temporary_file"
        echo -e "${RED}❌ Downloaded ${description} is unexpectedly small.${NC}" >&2
        return 1
    fi

    mv "$temporary_file" "$destination"
}

validate_platform() {
    if [ "$(uname -s)" != "Linux" ]; then
        echo -e "${RED}❌ setup.sh supports 64-bit Raspberry Pi OS only.${NC}" >&2
        return 1
    fi
    if [ "$(uname -m)" != "aarch64" ]; then
        echo -e "${RED}❌ A 64-bit ARM OS is required (expected aarch64).${NC}" >&2
        return 1
    fi
}

install_system_dependencies() {
    local packages=(
        build-essential
        ca-certificates
        cmake
        curl
        espeak-ng
        git
        libasound2-dev
        libblas-dev
        liblapack-dev
        portaudio19-dev
        python3-dev
        python3-tk
        python3-venv
    )

    require_command apt-get
    if [ "$EUID" -eq 0 ]; then
        apt-get update
        apt-get install -y "${packages[@]}"
    else
        require_command sudo
        sudo apt-get update
        sudo apt-get install -y "${packages[@]}"
    fi

    local command_name
    for command_name in cmake curl git nproc python3 tar; do
        require_command "$command_name"
    done
}

create_directories() {
    mkdir -p \
        "$PIPER_DIR" \
        "$BASE_DIR/voices" \
        "$BASE_DIR/sounds/greeting_sounds" \
        "$BASE_DIR/sounds/thinking_sounds" \
        "$BASE_DIR/sounds/ack_sounds" \
        "$BASE_DIR/sounds/error_sounds" \
        "$BASE_DIR/faces/idle" \
        "$BASE_DIR/faces/listening" \
        "$BASE_DIR/faces/thinking" \
        "$BASE_DIR/faces/speaking" \
        "$BASE_DIR/faces/error" \
        "$BASE_DIR/faces/warmup"
}

setup_whisper_cpp() {
    if [ ! -d "$WHISPER_DIR" ]; then
        git clone --depth 1 --branch "$WHISPER_CPP_VERSION" \
            https://github.com/ggml-org/whisper.cpp.git "$WHISPER_DIR"
    elif [ ! -f "$WHISPER_DIR/CMakeLists.txt" ]; then
        echo -e "${RED}❌ Existing whisper.cpp directory is not a valid checkout.${NC}"
        return 1
    else
        echo -e "${GREEN}Using existing Whisper.cpp checkout.${NC}"
    fi

    cmake -S "$WHISPER_DIR" -B "$WHISPER_DIR/build" \
        -DCMAKE_BUILD_TYPE=Release
    cmake --build "$WHISPER_DIR/build" --config Release -j "$(nproc)"

    download_file \
        "$WHISPER_MODEL_URL" "$WHISPER_MODEL" 100000000 \
        "Whisper base.en model"

    if [ ! -x "$WHISPER_BINARY" ]; then
        echo -e "${RED}❌ Whisper.cpp did not produce the expected binary and model.${NC}"
        return 1
    fi
}

setup_piper() {
    local archive
    local url

    if [ -x "$PIPER_BINARY" ]; then
        echo -e "${GREEN}Piper is already installed.${NC}"
        return 0
    fi

    archive="$(mktemp "$BASE_DIR/piper.tar.gz.XXXXXX")"
    url="https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/piper_linux_aarch64.tar.gz"
    if ! download_file "$url" "$archive" 1000000 "Piper archive"; then
        rm -f "$archive"
        return 1
    fi
    if ! tar -xzf "$archive" -C "$PIPER_DIR" --strip-components=1; then
        rm -f "$archive"
        echo -e "${RED}❌ Failed to extract Piper.${NC}" >&2
        return 1
    fi
    rm -f "$archive"

    if [ ! -x "$PIPER_BINARY" ]; then
        echo -e "${RED}❌ Piper did not produce the expected executable.${NC}" >&2
        return 1
    fi
}

setup_voices() {
    local piper_voice_base
    local bmo_release_base

    piper_voice_base="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/semaine/medium"
    bmo_release_base="https://github.com/brenpoly/be-more-agent/releases/download/${BMO_VOICE_RELEASE}"

    download_file \
        "$piper_voice_base/en_GB-semaine-medium.onnx" \
        "$PIPER_VOICE" 1000000 "default Piper voice"
    download_file \
        "$piper_voice_base/en_GB-semaine-medium.onnx.json" \
        "$PIPER_VOICE_CONFIG" 100 "default Piper voice configuration"
    download_file \
        "$bmo_release_base/bmo.onnx" \
        "$BMO_VOICE" 1000000 "custom BMO voice"
    download_file \
        "$bmo_release_base/bmo.onnx.json" \
        "$BMO_VOICE_CONFIG" 100 "custom BMO voice configuration"

    python3 -m json.tool "$PIPER_VOICE_CONFIG" >/dev/null
    python3 -m json.tool "$BMO_VOICE_CONFIG" >/dev/null
}

setup_python_environment() {
    if [ ! -x "$VENV_PYTHON" ]; then
        python3 -m venv "$VENV_DIR"
    fi

    "$VENV_PYTHON" -m pip install --upgrade pip
    "$VENV_PYTHON" -m pip install --force-reinstall --no-cache-dir sounddevice
    "$VENV_PYTHON" -m pip install -r "$BASE_DIR/requirements.txt"
    # OpenWakeWord declares a Linux TFLite dependency that has no Python 3.13
    # wheel. BMO uses ONNX exclusively, so install the compatible API without
    # that unused dependency after pip has installed the remaining packages.
    "$VENV_PYTHON" -m pip install --no-deps --upgrade "openwakeword==0.6.0"
}

setup_ollama_models() {
    if ! command -v ollama >/dev/null 2>&1; then
        echo -e "${RED}❌ Ollama is required. Install it from https://ollama.com/download/linux and rerun setup.${NC}" >&2
        return 1
    fi

    ollama pull "$TEXT_MODEL"
    ollama pull "$VISION_MODEL"
}

setup_wake_word() {
    "$VENV_PYTHON" - "$WAKE_WORD_MODEL" <<'PY'
from importlib.metadata import version
from pathlib import Path
import shutil
import sys
import tempfile

import openwakeword
from openwakeword.model import Model
from openwakeword.utils import download_models

destination = Path(sys.argv[1])
models_directory = Path(openwakeword.__file__).parent / "resources/models"
source = models_directory / "hey_jarvis_v0.1.onnx"
required_package_models = (
    models_directory / "melspectrogram.onnx",
    models_directory / "embedding_model.onnx",
    source,
)

if version("openwakeword") != "0.6.0":
    raise RuntimeError("openWakeWord 0.6.0 is required")
if not all(path.is_file() for path in required_package_models):
    download_models(model_names=["hey_jarvis_v0.1"])
if not all(path.is_file() for path in required_package_models):
    raise RuntimeError("openWakeWord did not provide its required ONNX models")

if not destination.is_file() or destination.stat().st_size < 10_000:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent,
        prefix=f".{destination.name}.part.",
        delete=False,
    ) as temporary:
        with source.open("rb") as source_file:
            shutil.copyfileobj(source_file, temporary)
        temporary_path = Path(temporary.name)
    temporary_path.replace(destination)

Model(
    wakeword_models=[str(destination)],
    inference_framework="onnx",
)
PY

    if [ ! -s "$WAKE_WORD_MODEL" ]; then
        echo -e "${RED}❌ Wake-word setup did not produce the expected model.${NC}" >&2
        return 1
    fi
}

verify_installation() {
    if [ ! -x "$WHISPER_BINARY" ] || [ ! -s "$WHISPER_MODEL" ]; then
        return 1
    fi
    if [ ! -x "$PIPER_BINARY" ] || [ ! -s "$PIPER_VOICE" ]; then
        return 1
    fi
    if [ ! -x "$VENV_PYTHON" ] || [ ! -s "$WAKE_WORD_MODEL" ]; then
        return 1
    fi

    "$VENV_PYTHON" - <<'PY'
import tkinter

import PIL
import ddgs
import numpy
import ollama
import onnxruntime
import openwakeword
import scipy
import sounddevice
PY

    if command -v rpicam-still >/dev/null 2>&1; then
        echo -e "${GREEN}Raspberry Pi camera tools detected.${NC}"
    else
        echo -e "${YELLOW}⚠️  rpicam-still was not found; camera features will be unavailable.${NC}"
    fi
}

main() {
    trap handle_error ERR

    echo -e "${GREEN}🤖 Be More Agent Raspberry Pi Setup${NC}"

    validate_platform

    echo -e "${YELLOW}[1/8] Installing system dependencies...${NC}"
    install_system_dependencies

    echo -e "${YELLOW}[2/8] Creating local directories...${NC}"
    create_directories

    echo -e "${YELLOW}[3/8] Setting up Whisper.cpp...${NC}"
    setup_whisper_cpp

    echo -e "${YELLOW}[4/8] Setting up Piper TTS...${NC}"
    setup_piper

    echo -e "${YELLOW}[5/8] Downloading voice models...${NC}"
    setup_voices

    echo -e "${YELLOW}[6/8] Installing Python libraries...${NC}"
    setup_python_environment

    echo -e "${YELLOW}[7/8] Pulling Ollama models...${NC}"
    setup_ollama_models

    echo -e "${YELLOW}[8/8] Installing and verifying the wake-word model...${NC}"
    setup_wake_word
    verify_installation

    echo -e "${GREEN}✨ Setup complete.${NC}"
    echo "Run: source venv/bin/activate && python agent.py"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
