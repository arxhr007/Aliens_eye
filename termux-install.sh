#!/data/data/com.termux/files/usr/bin/bash
# Aliens Eye - Termux Installation Script
# Improved installation script with error handling and better practices

# Colors for terminal output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Define paths
TERMUX_PREFIX="/data/data/com.termux/files/usr"
BIN_DIR="${TERMUX_PREFIX}/bin"
CONFIG_DIR="${TERMUX_PREFIX}/etc/aliens_eye"

# Function for clean error exit
cleanup() {
    echo -e "\n${RED}Installation aborted.${NC}"
    exit 1
}

# Trap errors
trap cleanup ERR

clear
echo -e "${BLUE}╔═══════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║      ${GREEN}Aliens Eye Termux Installation${BLUE}        ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════╝${NC}"
echo

# Check if source files exist
if [[ ! -f "aliens_eye.py" ]]; then
    echo -e "${RED}Error: aliens_eye.py not found in current directory.${NC}"
    exit 1
fi

if [[ ! -f "sites.json" ]]; then
    echo -e "${RED}Error: sites.json not found in current directory.${NC}"
    exit 1
fi

# Create config directory if it doesn't exist
echo -e "${GREEN}Setting up configuration directory...${NC}"
mkdir -p "${CONFIG_DIR}"

# Remove old installations if they exist
echo -e "${GREEN}Removing old installation (if any)...${NC}"
rm -f "${BIN_DIR}/aliens_eye" 2>/dev/null
rm -f "${BIN_DIR}/sites.json" 2>/dev/null

# Install program files
echo -e "${GREEN}Installing program files...${NC}"
cp "aliens_eye.py" "${BIN_DIR}/aliens_eye"
cp "sites.json" "${CONFIG_DIR}/sites.json"
chmod +x "${BIN_DIR}/aliens_eye"

# Create symlink to config file
ln -sf "${CONFIG_DIR}/sites.json" "${BIN_DIR}/sites.json"

# Verify installation
if [[ -x "${BIN_DIR}/aliens_eye" && -f "${CONFIG_DIR}/sites.json" ]]; then
    echo -e "\n${GREEN}✓ Installation completed successfully!${NC}"
    echo -e "${YELLOW}You can now run 'aliens_eye' from anywhere in Termux.${NC}"
    echo -e "${YELLOW}Configuration file is located at: ${CONFIG_DIR}/sites.json${NC}\n"
else
    echo -e "\n${RED}✗ Installation failed. Please check the error messages above.${NC}"
    exit 1
fi

exit 0
