#!/bin/bash
# Aliens Eye - Uninstall Script
# This script uninstalls Aliens Eye from both Linux and Termux environments

# Colors for terminal output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print banner
echo -e "${BLUE}╔═══════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║        ${RED}Aliens Eye Uninstaller${BLUE}              ║${NC}"
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
    ALT_BIN_DIR="/usr/bin"
    CONFIG_DIR="/etc/aliens_eye"
    REQUIRES_ROOT=true
    
    # Check for root permissions on Linux
    if [[ $(id -u) -ne 0 && "$REQUIRES_ROOT" = true ]]; then
        echo -e "${YELLOW}Root privileges are required for uninstallation on Linux.${NC}"
        echo -e "${YELLOW}Elevating privileges...${NC}"
        exec sudo bash "$0" "$@"
        exit $?
    fi
fi

# Function to remove files with status reporting
remove_file() {
    local file=$1
    if [ -e "$file" ]; then
        rm -f "$file"
        if [ $? -eq 0 ]; then
            echo -e "  ${GREEN}✓${NC} Removed: $file"
            return 0
        else
            echo -e "  ${RED}✗${NC} Failed to remove: $file"
            return 1
        fi
    else
        echo -e "  ${YELLOW}!${NC} Not found: $file"
        return 0
    fi
}

# Function to remove directory with status reporting
remove_dir() {
    local dir=$1
    if [ -d "$dir" ]; then
        rm -rf "$dir"
        if [ $? -eq 0 ]; then
            echo -e "  ${GREEN}✓${NC} Removed directory: $dir"
            return 0
        else
            echo -e "  ${RED}✗${NC} Failed to remove directory: $dir"
            return 1
        fi
    else
        echo -e "  ${YELLOW}!${NC} Directory not found: $dir"
        return 0
    fi
}

# Confirmation prompt
echo -e "${YELLOW}This will uninstall Aliens Eye from your system.${NC}"
echo -e "${YELLOW}Are you sure you want to continue? [y/N]${NC}"
read -r response
if [[ ! "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
    echo -e "${YELLOW}Uninstallation cancelled.${NC}"
    exit 0
fi

# Uninstall files
echo -e "\n${GREEN}Removing Aliens Eye files...${NC}"

# Remove binaries
remove_file "${BIN_DIR}/aliens_eye"

# Check alternative binary location for Linux
if [ "$REQUIRES_ROOT" = true ] && [ -e "${ALT_BIN_DIR}/aliens_eye" ]; then
    remove_file "${ALT_BIN_DIR}/aliens_eye"
fi

# Remove symlinks to configuration
remove_file "${BIN_DIR}/sites.json"
if [ "$REQUIRES_ROOT" = true ] && [ -e "${ALT_BIN_DIR}/sites.json" ]; then
    remove_file "${ALT_BIN_DIR}/sites.json"
fi

# Remove configuration directory
echo -e "\n${GREEN}Removing configuration files...${NC}"
remove_dir "${CONFIG_DIR}"

# Additional cleanup - remove any leftover files
echo -e "\n${GREEN}Checking for leftover files...${NC}"
if [ "$REQUIRES_ROOT" = true ]; then
    find /tmp -name "aliens_eye_*" -type f -exec rm -f {} \; 2>/dev/null
    if [ $? -eq 0 ]; then
        echo -e "  ${GREEN}✓${NC} Cleaned temporary files"
    else
        echo -e "  ${YELLOW}!${NC} No temporary files found or couldn't access /tmp"
    fi
fi

# Check for success
if [ ! -e "${BIN_DIR}/aliens_eye" ] && [ ! -d "${CONFIG_DIR}" ]; then
    if [ "$REQUIRES_ROOT" = true ] && [ -e "${ALT_BIN_DIR}/aliens_eye" ]; then
        echo -e "\n${RED}Partial uninstallation. Some files may remain in ${ALT_BIN_DIR}.${NC}"
        exit 1
    else
        echo -e "\n${GREEN}✓ Aliens Eye has been successfully uninstalled from your system!${NC}"
        if [ "$REQUIRES_ROOT" = true ]; then
            echo -e "${YELLOW}You may need to restart your terminal for changes to take effect.${NC}"
        fi
        exit 0
    fi
else
    echo -e "\n${RED}✗ Uninstallation may be incomplete. Some files could not be removed.${NC}"
    echo -e "${YELLOW}You may need to manually remove remaining files.${NC}"
    exit 1
fi
