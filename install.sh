#!/bin/bash
# Aliens Eye - Universal Installation Script
# This script installs Aliens Eye on both Linux and Termux environments

# Colors for terminal output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function for clean error exit
cleanup() {
    echo -e "\n${RED}Installation aborted.${NC}"
    exit 1
}

# Function to check for required commands
check_requirement() {
    command -v "$1" >/dev/null 2>&1 || {
        echo -e "${RED}Error: Required command '$1' not found. Please install it first.${NC}"
        return 1
    }
    return 0
}

# Trap errors
trap cleanup ERR

clear
echo -e "${BLUE}╔═══════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       ${GREEN}Aliens Eye Installation${BLUE}             ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════╝${NC}"
echo

# Detect environment (Linux or Termux)
if [ -d "/data/data/com.termux" ]; then
    echo -e "${YELLOW}Termux environment detected${NC}"
    # Termux paths
    PREFIX="/data/data/com.termux/files/usr"
    BIN_DIR="${PREFIX}/bin"
    CONFIG_DIR="${PREFIX}/etc/aliens_eye"
    REQUIRES_ROOT=false
else
    echo -e "${YELLOW}Linux environment detected${NC}"
    # Standard Linux paths
    PREFIX="/usr/local"
    BIN_DIR="${PREFIX}/bin"
    CONFIG_DIR="/etc/aliens_eye"
    REQUIRES_ROOT=true
    
    # Check for root on Linux
    if [[ $(id -u) -ne 0 && "$REQUIRES_ROOT" = true ]]; then
        echo -e "${YELLOW}Root privileges are required for installation on Linux.${NC}"
        echo -e "${YELLOW}Elevating privileges...${NC}"
        exec sudo bash "$0" "$@"
        exit $?
    fi
fi

# Check for required programs
echo -e "${GREEN}Checking requirements...${NC}"
check_requirement "pip" || { 
    echo -e "${RED}Python pip is required but not installed.${NC}"
    if [ "$REQUIRES_ROOT" = false ]; then
        echo -e "${YELLOW}Run 'pkg install python' in Termux to install it.${NC}"
    else
        echo -e "${YELLOW}Install Python and pip on your system and try again.${NC}"
    fi
    exit 1
}

# Check if source files exist
if [[ ! -f "aliens_eye.py" ]]; then
    echo -e "${RED}Error: aliens_eye.py not found in current directory.${NC}"
    exit 1
fi

if [[ ! -f "sites.json" ]]; then
    echo -e "${RED}Error: sites.json not found in current directory.${NC}"
    exit 1
fi

# Install dependencies if requirements.txt exists
if [[ -f "requirements.txt" ]]; then
    echo -e "${GREEN}Installing Python dependencies...${NC}"
    
    if [ "$REQUIRES_ROOT" = true ]; then
        # Use --break-system-packages for Linux (requires newer pip)
        pip_version=$(pip --version | awk '{print $2}' | cut -d. -f1)
        if [ "$pip_version" -ge 23 ]; then
            pip install -r requirements.txt --break-system-packages || {
                echo -e "${RED}Failed to install dependencies.${NC}"
                exit 1
            }
        else
            pip install -r requirements.txt || {
                echo -e "${RED}Failed to install dependencies.${NC}"
                exit 1
            }
        fi
    else
        # Termux doesn't need --break-system-packages
        pip install -r requirements.txt || {
            echo -e "${RED}Failed to install dependencies.${NC}"
            exit 1
        }
    fi
else
    echo -e "${YELLOW}No requirements.txt found, skipping dependency installation.${NC}"
fi

# Create config directory if it doesn't exist
echo -e "${GREEN}Setting up configuration directory...${NC}"
mkdir -p "${CONFIG_DIR}" || {
    echo -e "${RED}Failed to create configuration directory.${NC}"
    exit 1
}

# Remove old installations if they exist
echo -e "${GREEN}Cleaning up old installation (if any)...${NC}"
rm -f "${BIN_DIR}/aliens_eye" 2>/dev/null
rm -f "${BIN_DIR}/sites.json" 2>/dev/null

# Install program files
echo -e "${GREEN}Installing program files...${NC}"
cp "aliens_eye.py" "${BIN_DIR}/aliens_eye" || {
    echo -e "${RED}Failed to install executable.${NC}"
    exit 1
}

cp "sites.json" "${CONFIG_DIR}/sites.json" || {
    echo -e "${RED}Failed to install configuration.${NC}"
    exit 1
}

chmod +x "${BIN_DIR}/aliens_eye" || {
    echo -e "${RED}Failed to set executable permissions.${NC}"
    exit 1
}

# Create symlink to config file
ln -sf "${CONFIG_DIR}/sites.json" "${BIN_DIR}/sites.json"

# Verify installation
if [[ -x "${BIN_DIR}/aliens_eye" && -f "${CONFIG_DIR}/sites.json" ]]; then
    echo -e "\n${GREEN}✓ Installation completed successfully!${NC}"
    
    if [ "$REQUIRES_ROOT" = true ]; then
        echo -e "${YELLOW}You can now run 'aliens_eye' from anywhere in the terminal.${NC}"
    else
        echo -e "${YELLOW}You can now run 'aliens_eye' from anywhere in Termux.${NC}"
    fi
    
    echo -e "${YELLOW}Configuration file is located at: ${CONFIG_DIR}/sites.json${NC}\n"
else
    echo -e "\n${RED}✗ Installation failed. Please check the error messages above.${NC}"
    exit 1
fi

exit 0
