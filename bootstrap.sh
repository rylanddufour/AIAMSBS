#!/bin/bash
# Hermes Infrastructure Bootstrap Script
# Usage: curl -fsSL https://raw.githubusercontent.com/youruser/hermes-infrastructure/main/bootstrap.sh | bash
#
# This script prepares a server with:
# - Docker and Docker Compose
# - Hermes Agent with infrastructure skills
# - MCP servers for container, metrics, and GitHub management

set -e

# ============================================
# Configuration
# ============================================

# Repository URL for skills and configs
INFRA_REPO="${INFRA_REPO:-https://github.com/youruser/hermes-infrastructure.git}"
INFRA_BRANCH="${INFRA_BRANCH:-main}"

# Installation directories
INSTALL_BASE_DIR="${INSTALL_BASE_DIR:-$HOME}"
HERMES_HOME="${HERMES_HOME:-$INSTALL_BASE_DIR/.hermes}"
DOCKER_COMPOSE_VERSION="${DOCKER_COMPOSE_VERSION:-2.24.0}"

# Hermes configuration
HERMES_PORT="${HERMES_PORT:-9119}"
HERMES_USER="${HERMES_USER:-$USER}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ============================================
# Pre-flight Checks
# ============================================

check_prerequisites() {
    log_info "Running prerequisites check..."

    # Check if running as root (not recommended)
    if [ "$EUID" -eq 0 ]; then
        log_warn "Running as root is not recommended. Run as a regular user with sudo."
    fi

    # Check for required commands
    local missing_cmds=()
    for cmd in curl git; do
        if ! command -v $cmd &> /dev/null; then
            missing_cmds+=($cmd)
        fi
    done

    if [ ${#missing_cmds[@]} -ne 0 ]; then
        log_info "Installing missing dependencies: ${missing_cmds[*]}"
        sudo apt update
        sudo apt install -y "${missing_cmds[@]}" jq
    fi

    log_success "Prerequisites check complete"
}

# ============================================
# Docker Installation
# ============================================

install_docker() {
    log_info "Checking for Docker..."

    if command -v docker &> /dev/null; then
        log_success "Docker is already installed: $(docker --version)"
        return 0
    fi

    log_info "Installing Docker..."

    # Update package list
    sudo apt update

    # Install dependencies
    sudo apt install -y \
        apt-transport-https \
        ca-certificates \
        curl \
        gnupg \
        lsb-release

    # Add Docker GPG key
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

    # Add Docker repository
    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
        $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    # Install Docker
    sudo apt update
    sudo apt install -y \
        docker-ce \
        docker-ce-cli \
        containerd.io \
        docker-compose-plugin

    # Start and enable Docker
    sudo systemctl start docker
    sudo systemctl enable docker

    # Add current user to docker group
    sudo usermod -aG docker "$HERMES_USER"

    log_success "Docker installed successfully"
    log_warn "You may need to log out and back in for docker group membership to take effect"
}

# ============================================
# Docker Compose Standalone (optional)
# ============================================

install_docker_compose() {
    log_info "Checking Docker Compose..."

    # Check if docker compose plugin is available
    if docker compose version &> /dev/null; then
        log_success "Docker Compose plugin is available"
        return 0
    fi

    # Check for standalone docker-compose
    if command -v docker-compose &> /dev/null; then
        log_success "Docker Compose standalone is installed"
        return 0
    fi

    log_info "Installing Docker Compose standalone..."

    # Install docker-compose
    sudo curl -L "https://github.com/docker/compose/releases/download/v${DOCKER_COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose

    log_success "Docker Compose installed"
}

# ============================================
# Hermes Agent Installation
# ============================================

install_hermes() {
    log_info "Checking for Hermes Agent..."

    if [ -f "$HERMES_HOME/.local/bin/hermes" ]; then
        log_success "Hermes is already installed"
        return 0
    fi

    log_info "Installing Hermes Agent..."

    # Create Hermes home directory
    mkdir -p "$HERMES_HOME"

    # Install Hermes using official installer
    curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash

    # Add to PATH for current session
    export PATH="$HERMES_HOME/.local/bin:$PATH"

    # Add to .bashrc for persistence
    if ! grep -q 'hermes-infrastructure' ~/.bashrc 2>/dev/null; then
        echo '' >> ~/.bashrc
        echo '# Hermes Infrastructure' >> ~/.bashrc
        echo 'export PATH="$HOME/.hermes/.local/bin:$PATH"' >> ~/.bashrc
    fi

    log_success "Hermes Agent installed to $HERMES_HOME"
}

# ============================================
# Clone Infrastructure Repository
# ============================================

clone_infra_repo() {
    log_info "Cloning infrastructure repository..."

    local infra_dir="$INSTALL_BASE_DIR/hermes-infrastructure"

    if [ -d "$infra_dir/.git" ]; then
        log_info "Repository already exists, pulling latest..."
        cd "$infra_dir"
        git pull origin "$INFRA_BRANCH" || log_warn "Could not pull latest, using existing"
    else
        log_info "Cloning from $INFRA_REPO"
        git clone -b "$INFRA_BRANCH" "$INFRA_REPO" "$infra_dir"
    fi

    log_success "Infrastructure repository ready at $infra_dir"
    echo "$infra_dir"
}

# ============================================
# Install Skills
# ============================================

install_skills() {
    local infra_dir="$1"
    local skills_dir="$infra_dir/skills"

    log_info "Installing Hermes skills..."

    if [ ! -d "$skills_dir" ]; then
        log_warn "No skills directory found in repository"
        return 0
    fi

    # Create Hermes skills directory
    local hermes_skills_dir="$HERMES_HOME/skills"
    mkdir -p "$hermes_skills_dir"

    # Copy skills
    cp -r "$skills_dir/"* "$hermes_skills_dir/"

    local skill_count=$(find "$hermes_skills_dir" -maxdepth 1 -type d -not -name skills | wc -l)
    log_success "Installed $skill_count skills"
}

# ============================================
# Deploy MCP Servers
# ============================================

deploy_mcp_servers() {
    local infra_dir="$1"
    local mcp_compose="$infra_dir/docker-compose.mcp.yml"

    log_info "Deploying MCP servers..."

    if [ ! -f "$mcp_compose" ]; then
        log_warn "No MCP docker-compose found at $mcp_compose"
        return 0
    fi

    # Copy MCP compose to a working directory
    local mcp_dir="$INSTALL_BASE_DIR/mcp-servers"
    mkdir -p "$mcp_dir"
    cp "$mcp_compose" "$mcp_dir/docker-compose.yml"

    # Create .env file if needed
    if [ ! -f "$mcp_dir/.env" ]; then
        cat > "$mcp_dir/.env" <<EOF
# GitHub MCP - Create a token at https://github.com/settings/tokens
# GITHUB_PERSONAL_ACCESS_TOKEN=your_token_here

# PostgreSQL MCP - Uncomment and configure if needed
# POSTGRES_MCP_DATABASE_URI=postgresql://user:password@host:5432/dbname
EOF
        log_info "Created $mcp_dir/.env - edit to add API tokens"
    fi

    # Start MCP servers
    cd "$mcp_dir"
    docker compose up -d

    log_success "MCP servers deployed"
}

# ============================================
# Configure Hermes
# ============================================

configure_hermes() {
    log_info "Configuring Hermes..."

    local hermes_config="$HERMES_HOME/config.yaml"

    # Create basic config if it doesn't exist
    if [ ! -f "$hermes_config" ]; then
        cat > "$hermes_config" <<EOF
# Hermes Agent Configuration
# Generated by bootstrap.sh

profile: default

gateway:
  host: 0.0.0.0
  port: ${HERMES_PORT}

tools:
  enabled:
    - terminal
    - file
    - web
    - browser

# MCP Servers Configuration
mcp:
  enabled: true
  servers:
    docker:
      type: stdio
      command: docker
      args: ["run", "--rm", "-i", "--network=host", "-v", "/var/run/docker.sock:/var/run/docker.sock", "ghcr.io/docker/mcp-gateway:latest"]

# Skill Configuration
skills:
  auto_load: true
  directories:
    - skills/
EOF
        log_info "Created Hermes configuration"
    fi

    log_success "Hermes configured"
}

# ============================================
# Create Systemd Service (optional)
# ============================================

create_hermes_service() {
    log_info "Creating Hermes systemd service..."

    local service_file="/etc/systemd/system/hermes.service"

    if [ -f "$service_file" ]; then
        log_info "Hermes service already exists"
        return 0
    fi

    # Check if running as root
    if [ "$EUID" -ne 0 ]; then
        log_warn "Not running as root, skipping systemd service creation"
        log_info "To create the service manually, run:"
        log_info "  sudo bootstrap.sh --with-service"
        return 0
    fi

    cat > "$service_file" <<EOF
[Unit]
Description=Hermes Agent
After=network.target docker.service

[Service]
Type=simple
User=$HERMES_USER
WorkingDirectory=$HERMES_HOME
ExecStart=$HERMES_HOME/.local/bin/hermes gateway
Restart=always
RestartSec=10
Environment="PATH=$HERMES_HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable hermes.service

    log_success "Hermes systemd service created and enabled"
}

# ============================================
# Start Hermes
# ============================================

start_hermes() {
    log_info "Starting Hermes Agent..."

    # Try to start via systemd if available
    if systemctl is-enabled hermes.service &> /dev/null; then
        sudo systemctl start hermes
        log_success "Hermes started via systemd"
    else
        # Start in background
        export PATH="$HERMES_HOME/.local/bin:$PATH"
        nohup hermes gateway > "$HERMES_HOME/hermes.log" 2>&1 &
        sleep 3
        log_success "Hermes started in background"
    fi
}

# ============================================
# Verify Installation
# ============================================

verify_installation() {
    log_info "Verifying installation..."

    local errors=0

    # Check Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker not found"
        errors=$((errors + 1))
    else
        log_success "Docker: $(docker --version)"
    fi

    # Check Docker Compose
    if docker compose version &> /dev/null || command -v docker-compose &> /dev/null; then
        log_success "Docker Compose: available"
    else
        log_error "Docker Compose not found"
        errors=$((errors + 1))
    fi

    # Check Hermes
    if [ -f "$HERMES_HOME/.local/bin/hermes" ]; then
        log_success "Hermes: installed at $HERMES_HOME"
    else
        log_error "Hermes not found"
        errors=$((errors + 1))
    fi

    # Check skills
    local skill_count=$(find "$HERMES_HOME/skills" -maxdepth 1 -type d -not -name skills 2>/dev/null | wc -l)
    if [ "$skill_count" -gt 0 ]; then
        log_success "Skills: $skill_count installed"
    else
        log_warn "Skills: none found"
    fi

    # Check MCP servers
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q mcp; then
        log_success "MCP servers: running"
    else
        log_warn "MCP servers: not running (may need configuration)"
    fi

    # Check Hermes gateway
    if curl -s -o /dev/null -w "%{http_code}" "http://localhost:$HERMES_PORT/health" 2>/dev/null | grep -q "200"; then
        log_success "Hermes Gateway: running on port $HERMES_PORT"
    else
        log_warn "Hermes Gateway: not responding (may still be starting)"
    fi

    if [ $errors -eq 0 ]; then
        log_success "Installation verification complete!"
    else
        log_warn "Installation complete with $errors error(s)"
    fi
}

# ============================================
# Main
# ============================================

main() {
    echo ""
    echo "============================================"
    echo "  Hermes Infrastructure Bootstrap"
    echo "============================================"
    echo ""

    log_info "Installation base: $INSTALL_BASE_DIR"
    log_info "Hermes home: $HERMES_HOME"
    log_info "Infrastructure repo: $INFRA_REPO"
    echo ""

    check_prerequisites
    install_docker
    install_docker_compose
    install_hermes

    local infra_dir
    infra_dir=$(clone_infra_repo)

    install_skills "$infra_dir"
    configure_hermes

    # Only deploy MCP and start Hermes if Docker is running
    if docker info &> /dev/null; then
        deploy_mcp_servers "$infra_dir"
        start_hermes
    else
        log_warn "Docker not running, skipping MCP and Hermes startup"
        log_info "Start Docker and run again, or start manually:"
        log_info "  cd $INSTALL_BASE_DIR/mcp-servers && docker compose up -d"
        log_info "  hermes gateway"
    fi

    echo ""
    echo "============================================"
    echo "  Bootstrap Complete!"
    echo "============================================"
    echo ""

    verify_installation

    echo ""
    echo "Next steps:"
    echo "1. Log out and back in for docker group membership"
    echo "2. Edit $INSTALL_BASE_DIR/mcp-servers/.env with API tokens"
    echo "3. Access Hermes at http://localhost:$HERMES_PORT"
    echo ""
}

# Parse arguments
case "${1:-}" in
    --with-service)
        # Used when running with sudo to create systemd service
        shift
        main "$@"
        ;;
    --help|-h)
        echo "Usage: $0 [--with-service]"
        echo ""
        echo "Options:"
        echo "  --with-service  Create systemd service (requires root)"
        echo ""
        echo "Environment variables:"
        echo "  INFRA_REPO       GitHub repo URL (default: https://github.com/youruser/hermes-infrastructure.git)"
        echo "  INFRA_BRANCH    Git branch (default: main)"
        echo "  HERMES_PORT     Hermes gateway port (default: 9119)"
        echo "  HERMES_USER     User to run Hermes (default: current user)"
        echo "  INSTALL_BASE_DIR  Base installation directory (default: \$HOME)"
        ;;
    *)
        main "$@"
        ;;
esac