#!/bin/bash
# Hermes Infrastructure Bootstrap Script v2.1
# Usage: curl -fsSL https://raw.githubusercontent.com/rylanddufour/AIAMSBS/main/bootstrap.sh | bash -s -- --api-key YOUR_KEY --provider openrouter
#
# Options:
#   --api-key KEY       Your LLM provider API key (required for non-interactive)
#   --provider NAME    Provider: openai, anthropic, openrouter, google (default: openrouter)
#   --model MODEL      Model name (optional, will prompt if omitted)
#   --auto-deploy     Automatically deploy stack after setup (default: true)
#   --no-auto-deploy  Skip auto-deploy (manual mode)
#
# Interactive mode (no args):
#   curl ... | bash    # Prompts for API key and provider

set -e

# ============================================
# Configuration
# ============================================

INFRA_REPO="${INFRA_REPO:-https://github.com/rylanddufour/AIAMSBS.git}"
INFRA_BRANCH="${INFRA_BRANCH:-main}"
INSTALL_BASE_DIR="${INSTALL_BASE_DIR:-$HOME}"
HERMES_HOME="${HERMES_HOME:-$INSTALL_BASE_DIR/.hermes}"
DOCKER_COMPOSE_VERSION="${DOCKER_COMPOSE_VERSION:-2.24.0}"
HERMES_PORT="${HERMES_PORT:-9119}"
HERMES_USER="${HERMES_USER:-$USER}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ============================================
# CLI Argument Parsing
# ============================================

CLI_API_KEY=""
CLI_PROVIDER="openrouter"
CLI_MODEL=""
AUTO_DEPLOY=true

while [[ $# -gt 0 ]]; do
    case $1 in
        --api-key)
            CLI_API_KEY="$2"
            shift 2
            ;;
        --provider)
            CLI_PROVIDER="$2"
            shift 2
            ;;
        --model)
            CLI_MODEL="$2"
            shift 2
            ;;
        --auto-deploy)
            AUTO_DEPLOY=true
            shift
            ;;
        --no-auto-deploy)
            AUTO_DEPLOY=false
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --api-key KEY       Your LLM provider API key"
            echo "  --provider NAME     Provider: openai, anthropic, openrouter, google (default: openrouter)"
            echo "  --model MODEL       Model name (optional)"
            echo "  --auto-deploy       Automatically deploy stack after setup (default)"
            echo "  --no-auto-deploy    Skip auto-deploy"
            echo ""
            echo "Examples:"
            echo "  $0 --api-key sk-xxx --provider openrouter"
            echo "  $0 --api-key sk-xxx --provider openai --model gpt-4o"
            echo "  $0                  # Interactive mode"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# ============================================
# Provider Configuration
# ============================================

declare -A PROVIDER_ENV_VARS=(
    [openai]="OPENAI_API_KEY"
    [anthropic]="ANTHROPIC_API_KEY"
    [openrouter]="OPENROUTER_API_KEY"
    [google]="GOOGLE_API_KEY"
)

declare -A PROVIDER_MODELS=(
    [openai]="gpt-4o gpt-4o-mini gpt-4-turbo gpt-4"
    [anthropic]="claude-sonnet-4-20250514 claude-3-5-sonnet-20240620 claude-3-5-haiku-20240307 claude-3-opus-20240229"
    [openrouter]="openai/chatgpt-4o-latest openai/chatgpt-4o-mini anthropic/claude-sonnet-4 google/gemini-2.5-pro"
    [google]="gemini-2.5-pro gemini-2.0-flash gemini-1.5-pro"
)

# ============================================
# Interactive Selection Functions
# ============================================

interactive_select_provider() {
    echo ""
    echo "============================================"
    echo "  Select your LLM Provider"
    echo "============================================"
    echo ""
    echo "  [1] OpenAI"
    echo "  [2] Anthropic"
    echo "  [3] OpenRouter (default)"
    echo "  [4] Google"
    echo ""
    read -p "Enter choice [1-4]: " choice

    case $choice in
        1) PROVIDER="openai" ;;
        2) PROVIDER="anthropic" ;;
        3) PROVIDER="openrouter" ;;
        4) PROVIDER="google" ;;
        *) PROVIDER="openrouter" ;;
    esac

    echo "  Selected: $PROVIDER"
    echo ""
}

interactive_select_model() {
    local available_models="${PROVIDER_MODELS[$PROVIDER]}"
    local i=1
    local model_array=()
    
    echo "============================================"
    echo "  Select Model for $PROVIDER"
    echo "============================================"
    echo ""
    
    for model in $available_models; do
        echo "  [$i] $model"
        model_array+=("$model")
        i=$((i + 1))
    done
    echo ""
    echo "  [$(($i))] Custom model (enter name)"
    echo ""
    
    read -p "Enter choice [1-$(($i))]: " choice
    
    if [ "$choice" -ge 1 ] && [ "$choice" -le ${#model_array[@]} ]; then
        MODEL="${model_array[$((choice-1))]}"
    elif [ "$choice" -eq $(($i)) ]; then
        read -p "Enter model name: " MODEL
    else
        MODEL=""
    fi
    
    echo "  Selected: ${MODEL:-default}"
    echo ""
}

interactive_get_api_key() {
    echo "============================================"
    echo "  Enter API Key"
    echo "============================================"
    echo ""
    echo "  Provider: $PROVIDER"
    echo "  Model: ${MODEL:-default}"
    echo ""
    read -p "  API Key: " -s API_KEY
    echo ""
    echo ""
}

# ============================================
# Provider/Model Resolution
# ============================================

resolve_provider_model() {
    # If CLI args provided, use them
    if [ -n "$CLI_API_KEY" ]; then
        PROVIDER="$CLI_PROVIDER"
        MODEL="$CLI_MODEL"
        API_KEY="$CLI_API_KEY"
        
        # Validate provider
        if [ -z "${PROVIDER_ENV_VARS[$PROVIDER]}" ]; then
            log_error "Unknown provider: $PROVIDER"
            log_info "Valid providers: ${!PROVIDER_ENV_VARS[@]}"
            exit 1
        fi
        
        return 0
    fi
    
    # Interactive mode
    interactive_select_provider
    interactive_select_model
    interactive_get_api_key
}

# ============================================
# Pre-flight Checks
# ============================================

check_prerequisites() {
    log_info "Running prerequisites check..."

    if [ "$EUID" -eq 0 ]; then
        log_warn "Running as root is not recommended. Run as a regular user with sudo."
    fi

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

    sudo apt update
    sudo apt install -y \
        apt-transport-https \
        ca-certificates \
        curl \
        gnupg \
        lsb-release

    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
        $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt update
    sudo apt install -y \
        docker-ce \
        docker-ce-cli \
        containerd.io \
        docker-compose-plugin

    sudo systemctl start docker
    sudo systemctl enable docker
    sudo usermod -aG docker "$HERMES_USER"

    log_success "Docker installed successfully"
    log_warn "You may need to log out and back in for docker group membership"
}

# ============================================
# Docker Compose
# ============================================

install_docker_compose() {
    log_info "Checking Docker Compose..."

    if docker compose version &> /dev/null; then
        log_success "Docker Compose plugin is available"
        return 0
    fi

    if command -v docker-compose &> /dev/null; then
        log_success "Docker Compose standalone is installed"
        return 0
    fi

    log_info "Installing Docker Compose standalone..."

    sudo curl -L "https://github.com/docker/compose/releases/download/v${DOCKER_COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose

    log_success "Docker Compose installed"
}

# ============================================
# Hermes Installation
# ============================================

install_hermes() {
    log_info "Checking for Hermes Agent..."

    if [ -f "$HERMES_HOME/hermes-agent/venv/bin/hermes" ]; then
        log_success "Hermes is already installed"
        return 0
    fi

    log_info "Installing Hermes Agent..."

    mkdir -p "$HERMES_HOME"
    # --skip-setup bypasses the interactive setup wizard
    curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash -s -- --skip-setup

    export PATH="$HERMES_HOME/.local/bin:$PATH"

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

    local infra_dir="$INSTALL_BASE_DIR/AIAMSBS"

    if [ -d "$infra_dir/.git" ]; then
        log_info "Repository already exists, pulling latest..."
        cd "$infra_dir"
        git pull origin "$INFRA_BRANCH" 2>/dev/null || log_warn "Could not pull latest"
    else
        log_info "Cloning from $INFRA_REPO"
        git clone -b "$INFRA_BRANCH" "$INFRA_REPO" "$infra_dir"
    fi

    log_success "Infrastructure repository ready at $infra_dir"
    echo "$infra_dir"
}

# ============================================
# Configure Hermes with API Key
# ============================================

configure_hermes_api() {
    local env_file="$HERMES_HOME/.env"
    local env_var="${PROVIDER_ENV_VARS[$PROVIDER]}"
    
    log_info "Configuring Hermes with $PROVIDER provider..."
    
    # Write .env file
    cat > "$env_file" <<EOF
# LLM Provider Configuration
# Generated by bootstrap.sh v2.1

# Provider: $PROVIDER
# Model: ${MODEL:-default}"
${env_var}=${API_KEY}

# Allow all users (change for production security)
GATEWAY_ALLOW_ALL_USERS=true
EOF

    log_success "API key configured for $PROVIDER"
    
    # Update config.yaml using hermes model command (validates model)
    if [ -f "$HERMES_HOME/hermes-agent/venv/bin/hermes" ]; then
        cd "$HERMES_HOME/hermes-agent"
        source venv/bin/activate
        
        log_info "Setting Hermes model..."
        
        # Try to set model via hermes command
        if [ -n "$MODEL" ]; then
            hermes model --set "$PROVIDER" "$MODEL" 2>/dev/null && \
                log_success "Model set to $MODEL" || \
                log_warn "Could not validate model, using defaults"
        else
            hermes model --set "$PROVIDER" 2>/dev/null && \
                log_success "Provider configured" || \
                log_warn "Could not configure provider"
        fi
    fi
}

# ============================================
# Auto-Deploy Stack
# ============================================

auto_deploy_stack() {
    log_info "Starting auto-deploy of monitoring stack..."
    
    local infra_dir="$INSTALL_BASE_DIR/AIAMSBS"
    
    cd "$HERMES_HOME/hermes-agent"
    source venv/bin/activate
    
    # Add hermes command to PATH (installed to ~/.local/bin)
    export PATH="$HERMES_HOME/.local/bin:$PATH"
    
    # Run Hermes with explicit config-based deployment
    log_info "Running Hermes to deploy stack using config files in $infra_dir..."
    
    local deploy_prompt="Deploy the monitoring stack using the configuration files in $infra_dir. Specifically:
1. Read docker-compose.yml for the stack definition
2. Read config/*.yml for service configurations
3. Run 'docker compose up -d' to deploy the stack

The stack includes: Traefik, Prometheus, Grafana, Loki, Alloy, Portainer, and Hermes WebUI."

    if hermes --yolo chat -q "$deploy_prompt"; then
        log_success "Stack deployed successfully!"
    else
        log_error "Stack deployment failed. You can retry manually with:"
        log_info "  cd $infra_dir && docker compose up -d"
    fi
}
# ============================================
# Verify Installation
# ============================================

verify_installation() {
    log_info "Verifying installation..."

    local errors=0

    if ! command -v docker &> /dev/null; then
        log_error "Docker not found"
        errors=$((errors + 1))
    else
        log_success "Docker: $(docker --version)"
    fi

    if docker compose version &> /dev/null || command -v docker-compose &> /dev/null; then
        log_success "Docker Compose: available"
    else
        log_error "Docker Compose not found"
        errors=$((errors + 1))
    fi

    if [ -f "$HERMES_HOME/hermes-agent/venv/bin/hermes" ]; then
        log_success "Hermes: installed"
    else
        log_error "Hermes not found"
        errors=$((errors + 1))
    fi

    if [ -f "$HERMES_HOME/.env" ]; then
        log_success "API key: configured"
    else
        log_warn "API key: not configured"
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
    # Resolve provider/model (CLI or interactive)
    resolve_provider_model
    
    echo ""
    echo "============================================"
    echo "  Hermes Infrastructure Bootstrap v2.1"
    echo "============================================"
    echo ""
    echo "  Provider: $PROVIDER"
    echo "  Model: ${MODEL:-default}"
    echo "  Auto-deploy: $AUTO_DEPLOY"
    echo ""

    check_prerequisites
    install_docker
    install_docker_compose
    install_hermes
    
    local infra_dir
    infra_dir=$(clone_infra_repo)
    
    configure_hermes_api
    
    if [ "$AUTO_DEPLOY" = true ]; then
        auto_deploy_stack
    else
        log_info "Skipping auto-deploy (--no-auto-deploy)"
        log_info "To deploy manually, run:"
        log_info "  hermes chat -q 'Deploy the monitoring stack from https://.../GOAL.md'"
    fi

    echo ""
    echo "============================================"
    echo "  Bootstrap Complete!"
    echo "============================================"
    echo ""
    echo "  Services:"
    echo "    - Grafana:       http://localhost:3000 (admin/admin123)"
    echo "    - Prometheus:    http://localhost:9090"
    echo "    - Loki:          http://localhost:3100"
    echo "    - Hermes WebUI:   http://localhost:8787"
    echo "    - Portainer:     https://localhost:9443 (admin/admin123)"
    echo "    - Traefik:       http://localhost:8080"
    echo ""
    echo "  To message Hermes (configure platform manually):"
    echo "    hermes gateway setup <platform>"
    echo ""
    
    verify_installation
}

main "$@"