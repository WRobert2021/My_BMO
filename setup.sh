#!/bin/bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BASE_DIR"

# Define colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

WHISPER_CPP_VERSION="${WHISPER_CPP_VERSION:-v1.9.2}"
WHISPER_BINARY_RELATIVE="whisper.cpp/build/bin/whisper-cli"
WHISPER_MODEL_RELATIVE="whisper.cpp/models/ggml-base.en.bin"
WHISPER_DIR="$BASE_DIR/whisper.cpp"
WHISPER_BINARY="$BASE_DIR/$WHISPER_BINARY_RELATIVE"
WHISPER_MODEL="$BASE_DIR/$WHISPER_MODEL_RELATIVE"

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

    if [ ! -s "$WHISPER_MODEL" ]; then
        sh "$WHISPER_DIR/models/download-ggml-model.sh" base.en
    else
        echo -e "${GREEN}Whisper base.en model is already present.${NC}"
    fi

    if [ ! -x "$WHISPER_BINARY" ] || [ ! -s "$WHISPER_MODEL" ]; then
        echo -e "${RED}❌ Whisper.cpp setup did not produce the expected binary and model.${NC}"
        return 1
    fi
}

echo -e "${GREEN}🤖 Pi Local Assistant Setup Script${NC}"

# 1. Install System Dependencies (The "Hidden" Requirements)
echo -e "${YELLOW}[1/8] Installing System Tools (apt)...${NC}"
sudo apt update
sudo apt install -y python3-tk python3-dev libasound2-dev portaudio19-dev liblapack-dev libblas-dev cmake build-essential espeak-ng git

# 2. Create Folders
echo -e "${YELLOW}[2/8] Creating Folders...${NC}"
mkdir -p piper
mkdir -p voices # Added for custom BMO models
mkdir -p sounds/greeting_sounds
mkdir -p sounds/thinking_sounds
mkdir -p sounds/ack_sounds
mkdir -p sounds/error_sounds
mkdir -p faces/idle
mkdir -p faces/listening
mkdir -p faces/thinking
mkdir -p faces/speaking
mkdir -p faces/error
mkdir -p faces/warmup

# 3. Build Whisper.cpp and download its default model
echo -e "${YELLOW}[3/8] Setting up Whisper.cpp...${NC}"
setup_whisper_cpp

# 4. Download Piper (Architecture Check)
echo -e "${YELLOW}[4/8] Setting up Piper TTS...${NC}"
ARCH=$(uname -m)
if [ "$ARCH" == "aarch64" ]; then
    # FIXED: Using the specific 2023.11.14-2 release known to work on Pi
    wget -O piper.tar.gz https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz
    tar -xvf piper.tar.gz -C piper --strip-components=1
    rm piper.tar.gz
else
    echo -e "${RED}⚠️  Not on Raspberry Pi (aarch64). Skipping Piper download.${NC}"
fi

# 5. Download Voice Models
echo -e "${YELLOW}[5/8] Downloading Voice Models...${NC}"
# Download default Piper voice as fallback
cd piper
wget -nc -O en_GB-semaine-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/semaine/medium/en_GB-semaine-medium.onnx
wget -nc -O en_GB-semaine-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/semaine/medium/en_GB-semaine-medium.onnx.json
cd ..

# Download Custom BMO Voice
echo -e "${YELLOW}Downloading custom BMO voice...${NC}"
curl -L -o voices/bmo-custom.onnx "https://github.com/brenpoly/be-more-agent/releases/latest/download/bmo.onnx"
curl -L -o voices/bmo-custom.onnx.json "https://github.com/brenpoly/be-more-agent/releases/latest/download/bmo.onnx.json"

# 6. Install Python Libraries
echo -e "${YELLOW}[6/8] Installing Python Libraries...${NC}"
# Check if venv exists, if not create it
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip
# Force rebuild sounddevice to link against the newly installed PortAudio dev libraries
pip install --force-reinstall --no-cache-dir sounddevice
pip install -r requirements.txt

# 7. Pull AI Models
echo -e "${YELLOW}[7/8] Checking AI Models...${NC}"
if command -v ollama &> /dev/null; then
    ollama pull gemma3:1b
    ollama pull moondream
else
    echo -e "${RED}❌ Ollama not found. Please install it manually.${NC}"
fi

# 8. OpenWakeWord Model (Added this back so the user has a default)
echo -e "${YELLOW}[8/8] Checking the wake-word model...${NC}"
if [ ! -f "wakeword.onnx" ]; then
    echo -e "${YELLOW}Downloading default 'Hey Jarvis' wake word...${NC}"
    curl -L -o wakeword.onnx https://github.com/dscripka/openWakeWord/raw/main/openwakeword/resources/models/hey_jarvis_v0.1.onnx
fi

echo -e "${GREEN}✨ Setup Complete! Run 'source venv/bin/activate' then 'python agent.py'${NC}"
