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

    # Install Node.js 20+ (required for Hermes Dashboard web UI build)
    if ! command -v node &> /dev/null; then
        log_info "Installing Node.js (required for Hermes Dashboard web UI)..."
        curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
        sudo apt install -y nodejs
        log_success "Node.js $(node --version) installed"
    else
        log_success "Node.js: $(node --version)"
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

    # Apply provider + model to the default profile's config.yaml
    if [ -f "$HERMES_HOME/hermes-agent/venv/bin/hermes" ]; then
        local hermes_bin="$HERMES_HOME/hermes-agent/venv/bin/hermes"

        log_info "Setting default profile: provider=$PROVIDER model=${MODEL:-(unchanged)}..."

        # Set provider (always — even when --model omitted, --provider still applies)
        "$hermes_bin" config set model.provider "$PROVIDER" 2>/dev/null && \
            log_success "Provider set to $PROVIDER" || \
            log_warn "Could not set provider; leaving upstream default"

        # Set model only when explicitly passed
        if [ -n "$MODEL" ]; then
            "$hermes_bin" config set model.default "$MODEL" 2>/dev/null && \
                log_success "Model set to $MODEL" || \
                log_warn "Could not set model; leaving upstream default"
        fi
    fi
}

# ============================================
# Build Hermes Dashboard Web UI
# ============================================

build_dashboard_ui() {
    local web_dir="$HERMES_HOME/hermes-agent/web"

    if [ ! -d "$web_dir" ]; then
        log_warn "Hermes Dashboard web UI directory not found at $web_dir, skipping build"
        return 0
    fi

    log_info "Building Hermes Dashboard web UI (Vite)..."
    (cd "$web_dir" && npm install --silent && npm run build) || {
        log_error "Web UI build failed; dashboard will not start"
        return 1
    }
    log_success "Hermes Dashboard web UI built"
    return 0
}

# ============================================
# Start Hermes Dashboard
# ============================================

start_hermes_dashboard() {
    log_info "Starting Hermes Dashboard on port $HERMES_PORT..."

    # Skip if already running
    if curl -s "http://localhost:$HERMES_PORT" > /dev/null 2>&1; then
        log_success "Hermes Dashboard is already running on port $HERMES_PORT"
        return 0
    fi

    # Ensure logs directory exists with correct ownership
    mkdir -p "$HERMES_HOME/logs"

    # Launch dashboard in background
    (cd "$HERMES_HOME/hermes-agent" && \
        source venv/bin/activate && \
        nohup hermes dashboard --port "$HERMES_PORT" --host 0.0.0.0 --insecure --skip-build \
            > "$HERMES_HOME/logs/dashboard.log" 2>&1 &)

    # Wait for it to respond
    local retries=30
    while [ $retries -gt 0 ]; do
        if curl -s "http://localhost:$HERMES_PORT" > /dev/null 2>&1; then
            log_success "Hermes Dashboard started on port $HERMES_PORT"
            return 0
        fi
        sleep 1
        retries=$((retries - 1))
    done

    log_error "Failed to start Hermes Dashboard"
    log_info "Check logs at: $HERMES_HOME/logs/dashboard.log"
    return 1
}

# ============================================
# Install Grafana Skills (grafana-core + grafana-lgtm)
# ============================================

install_grafana_skills() {
    local skills_dir="$HERMES_HOME/skills/grafana"
    local tmp_dir
    tmp_dir=$(mktemp -d)

    log_info "Installing grafana-core and grafana-lgtm skills from grafana/skills..."

    if ! command -v git &> /dev/null; then
        log_warn "git not available; skipping grafana skills install"
        rm -rf "$tmp_dir"
        return 0
    fi

    if ! git clone --depth 1 --quiet https://github.com/grafana/skills.git "$tmp_dir/grafana-skills" 2>/dev/null; then
        log_warn "Could not clone grafana/skills; skipping skills install"
        rm -rf "$tmp_dir"
        return 0
    fi

    local installed=0
    for plugin in grafana-core grafana-lgtm; do
        if [ ! -d "$tmp_dir/grafana-skills/skills/$plugin" ]; then
            log_warn "Plugin $plugin not found in grafana/skills repo; skipping"
            continue
        fi
        for skill_dir in "$tmp_dir/grafana-skills/skills/$plugin"/*/; do
            [ -d "$skill_dir" ] || continue
            local skill_name
            skill_name=$(basename "$skill_dir")
            if [ -f "$skill_dir/SKILL.md" ]; then
                mkdir -p "$skills_dir/$skill_name"
                cp -r "$skill_dir/." "$skills_dir/$skill_name/"
                log_success "Installed skill: grafana/$skill_name"
                installed=$((installed + 1))
            fi
        done
    done

    rm -rf "$tmp_dir"

    if [ "$installed" -gt 0 ]; then
        log_success "Installed $installed Grafana skill(s) into $skills_dir"
    else
        log_warn "No Grafana skills were installed"
    fi
}

# ============================================
# Create Grafana Service Account for MCP
# ============================================

create_grafana_mcp_service_account() {
    local grafana_url="http://localhost:3000"
    local admin_user="admin"
    local admin_pass="${GRAFANA_PASSWORD:-admin123}"
    local secrets_dir="$HERMES_HOME/secrets"
    local secrets_file="$secrets_dir/grafana-mcp.env"

    log_info "Creating Grafana service account for MCP..."

    # Wait for Grafana to be healthy (up to 60s)
    local attempts=0
    while [ $attempts -lt 30 ]; do
        if curl -sf "${grafana_url}/api/health" >/dev/null 2>&1; then
            break
        fi
        sleep 2
        attempts=$((attempts + 1))
    done

    if [ $attempts -eq 30 ]; then
        log_warn "Grafana not reachable at $grafana_url; skipping SA creation"
        log_warn "Deploy the main stack first (docker compose up -d), then re-run this step"
        return 0
    fi

    # Check if service account + token already exist (idempotent re-runs)
    if [ -f "$secrets_file" ] && grep -q "GRAFANA_MCP_SERVICE_ACCOUNT_TOKEN=glsa_" "$secrets_file" 2>/dev/null; then
        log_info "Grafana MCP service account token already exists at $secrets_file"
        # shellcheck disable=SC1090
        set -a; source "$secrets_file"; set +a
        return 0
    fi

    # Create service account
    local sa_response
    sa_response=$(curl -sf -u "${admin_user}:${admin_pass}" \
        -H "Content-Type: application/json" \
        -X POST "${grafana_url}/api/serviceaccounts" \
        -d '{"name":"aiamsbs-mcp","role":"Admin","isDisabled":false}' 2>/dev/null) || {
        log_warn "Could not create Grafana service account; skipping"
        return 0
    }

    local sa_id
    sa_id=$(echo "$sa_response" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null || echo "")

    if [ -z "$sa_id" ]; then
        log_warn "Service account creation returned no id; skipping"
        return 0
    fi

    # Create token for the service account
    local token_response
    token_response=$(curl -sf -u "${admin_user}:${admin_pass}" \
        -H "Content-Type: application/json" \
        -X POST "${grafana_url}/api/serviceaccounts/${sa_id}/tokens" \
        -d '{"name":"aiamsbs-mcp-token"}' 2>/dev/null) || {
        log_warn "Could not create service account token; skipping"
        return 0
    }

    local token
    token=$(echo "$token_response" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('key',''))" 2>/dev/null || echo "")

    if [ -z "$token" ]; then
        log_warn "Token creation returned no key; skipping"
        return 0
    fi

    # Persist token to secrets file
    mkdir -p "$secrets_dir"
    cat > "$secrets_file" <<EOF
# Grafana MCP service account token
# Generated by bootstrap.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Service Account: aiamsbs-mcp (id: ${sa_id})
# Source: ${grafana_url}/admin/serviceaccounts
GRAFANA_MCP_SERVICE_ACCOUNT_TOKEN=${token}
EOF
    chmod 600 "$secrets_file"

    # Export for current shell so docker compose picks it up
    export GRAFANA_MCP_SERVICE_ACCOUNT_TOKEN="$token"

    log_success "Grafana service account created (id=${sa_id}); token saved to $secrets_file"
}

# ============================================
# Deploy MCP Stack (grafana-mcp)
# ============================================

deploy_mcp_stack() {
    local infra_dir
    infra_dir=$(clone_infra_repo)
    local mcp_compose="$infra_dir/docker-compose.mcp.yml"

    if [ ! -f "$mcp_compose" ]; then
        log_warn "MCP compose file not found at $mcp_compose; skipping"
        return 0
    fi

    log_info "Deploying MCP stack..."

    # Source the secrets file so GRAFANA_MCP_SERVICE_ACCOUNT_TOKEN is in env
    if [ -f "$HERMES_HOME/secrets/grafana-mcp.env" ]; then
        set -a
        # shellcheck disable=SC1090
        source "$HERMES_HOME/secrets/grafana-mcp.env"
        set +a
    fi

    if [ -z "${GRAFANA_MCP_SERVICE_ACCOUNT_TOKEN:-}" ]; then
        log_warn "GRAFANA_MCP_SERVICE_ACCOUNT_TOKEN not set; cannot deploy MCP"
        return 0
    fi

    # sudo -E preserves env vars (the token) into the root context
    if sudo -E docker compose -f "$mcp_compose" up -d 2>&1 | tail -5; then
        log_success "MCP stack deployed (grafana-mcp on port 8000)"
    else
        log_warn "MCP stack deployment failed; continuing"
        return 0
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
    build_dashboard_ui
    start_hermes_dashboard

    if [ "$AUTO_DEPLOY" = true ]; then
        auto_deploy_stack
    else
        log_info "Skipping auto-deploy (--no-auto-deploy)"
        log_info "To deploy manually, run:"
        log_info "  hermes chat -q 'Deploy the monitoring stack from https://.../GOAL.md'"
    fi

    # Post-install steps: skills install, MCP service account, MCP deploy
    install_grafana_skills
    create_grafana_mcp_service_account
    deploy_mcp_stack

    echo ""
    echo "============================================"
    echo "  Bootstrap Complete!"
    echo "============================================"
    echo ""
    echo "  Services:"
    echo "    - Grafana:        http://localhost:3000 (admin/admin123)"
    echo "    - Prometheus:     http://localhost:9090"
    echo "    - Loki:           http://localhost:3100"
    echo "    - Alloy:          http://localhost:12345"
    echo "    - Hermes Gateway: http://localhost:$HERMES_PORT"
    echo ""
    echo "  🔒 To restrict port $HERMES_PORT to specific IPs:"
    echo "      sudo ufw allow from <your-ip> to any port $HERMES_PORT"
    echo "      sudo ufw enable"
    echo ""
    echo "  To message Hermes (configure platform manually):"
    echo "    hermes gateway setup <platform>"
    echo ""

    verify_installation
}

main "$@"