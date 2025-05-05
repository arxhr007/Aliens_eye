#!/bin/bash
# aliens_eye - Installation script

set -e  # Exit immediately if a command exits with a non-zero status

# Colors for terminal output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Function for clean error exit
cleanup() {
    echo -e "${RED}Installation aborted.${NC}"
    exit 1
}

# Trap errors
trap cleanup ERR

# Check if running as root
if [[ $(id -u) -ne 0 ]]; then
    echo -e "${YELLOW}Root privileges are required for installation.${NC}"
    echo "Elevating privileges..."
    exec sudo bash "$0" "$@"
    exit $?
fi

clear
echo -e "${GREEN}===== Aliens Eye Installer =====${NC}"
echo

# Define installation paths
INSTALL_DIR="/usr/local/bin"
CONFIG_DIR="/etc/aliens_eye"

# Create config directory if it doesn't exist
mkdir -p "${CONFIG_DIR}"

echo -e "${YELLOW}NOTE: An active internet connection is required to install dependencies.${NC}"
echo

# Countdown
for i in 3 2 1; do
    echo -ne "Starting installation in ${i}...\r"
    sleep 1
done
echo -e "\n"

# Check if requirements.txt exists
if [[ ! -f "requirements.txt" ]]; then
    echo -e "${RED}Error: requirements.txt not found in current directory.${NC}"
    exit 1
fi

# Check if source files exist
if [[ ! -f "aliens_eye.py" ]]; then
    echo -e "${RED}Error: aliens_eye.py not found in current directory.${NC}"
    exit 1
fi

if [[ ! -f "sites.json" ]]; then
    echo -e "${RED}Error: sites.json not found in current directory.${NC}"
    exit 1
fi

# Install Python dependencies
echo -e "${GREEN}Installing Python dependencies...${NC}"
pip install -r requirements.txt --break-system-packages || {
    echo -e "${RED}Failed to install Python dependencies.${NC}"
    exit 1
}

# Install program files
echo -e "${GREEN}Installing program files...${NC}"

# Remove old installations if they exist
if [[ -f "${INSTALL_DIR}/aliens_eye" ]]; then
    rm "${INSTALL_DIR}/aliens_eye"
fi

if [[ -f "${CONFIG_DIR}/sites.json" ]]; then
    # Backup existing config
    echo "Backing up existing configuration..."
    cp "${CONFIG_DIR}/sites.json" "${CONFIG_DIR}/sites.json.backup"
fi

# Install new files
cp aliens_eye.py "${INSTALL_DIR}/aliens_eye"
cp sites.json "${CONFIG_DIR}/sites.json"
chmod +x "${INSTALL_DIR}/aliens_eye"

# Create a symbolic link to the configuration
ln -sf "${CONFIG_DIR}/sites.json" "${INSTALL_DIR}/sites.json" 2>/dev/null || true

# Verify installation
if [[ -x "${INSTALL_DIR}/aliens_eye" && -f "${CONFIG_DIR}/sites.json" ]]; then
    echo -e "\n${GREEN}✓ Installation completed successfully!${NC}"
    echo -e "You can now run 'aliens_eye' from anywhere in the terminal."
    echo -e "Configuration file is located at: ${CONFIG_DIR}/sites.json"
else
    echo -e "\n${RED}✗ Installation failed. Please check the error messages above.${NC}"
    exit 1
fi

exit 0
