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

# log_* writes to stderr so it cannot contaminate $(...) command substitutions.
# Functions that need to return a value via stdout (like clone_infra_repo)
# must only emit the value to stdout — informational logging must go to stderr.
log_info() { echo -e "${BLUE}[INFO]${NC} $1" >&2; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1" >&2; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1" >&2; }
log_error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }

# ============================================
# CLI Argument Parsing
# ============================================

CLI_API_KEY=""
CLI_PROVIDER="openrouter"
CLI_MODEL=""
AUTO_DEPLOY=true
DASHBOARD_USER="admin"
INSTALL_IT_ADMIN=false

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
        --dashboard-user)
            DASHBOARD_USER="$2"
            shift 2
            ;;
        --profile)
            case "$2" in
                it_admin)
                    INSTALL_IT_ADMIN=true
                    ;;
                all)
                    INSTALL_IT_ADMIN=true
                    ;;
                linux_admin|network_admin|windows_admin|vsphere_admin)
                    echo "Profile '$2' is retired (see BACKLOG #16/#17/#18/#19 — collapsed into 'it_admin'). Ignoring."
                    exit 0
                    ;;
                *)
                    echo "Unknown profile: $2"
                    exit 1
                    ;;
            esac
            shift 2
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
            echo "  --dashboard-user USER   Username for the Hermes dashboard (default: admin)"
            echo "  --profile NAME     Install specialist profile(s). NAME = it_admin,"
            echo "                     or all. (Replaces the retired linux_admin/"
            echo "                     network_admin/windows_admin/vsphere_admin split — see BACKLOG #20)"
            echo "                     Multiple --profile flags OK. Default: default profile only."
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
    # Return value: ONLY the path. log_* above goes to stderr, so stdout is clean
    # for `$(clone_infra_repo)` capture. See log_* definitions for rationale.
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
# Install default Profile SOUL.md
# ============================================
# The default Profile's persona lives at $INFRA_DIR/profiles/default/SOUL.md
# (shipped in this repo). Copy it into $HERMES_HOME so the runtime picks it
# up — either alongside the top-level config.yaml (single-profile mode) or
# under profiles/default/ (multi-profile mode). Auto-detect which layout
# the Customer is using by checking for an existing profiles/ directory.
# Falls back to writing to both locations so the install is robust against
# either layout the runtime ends up using.

install_default_profile_soul() {
    local source="$INFRA_DIR/profiles/default/SOUL.md"
    local multi_target_dir multi_target single_target

    if [ ! -f "$source" ]; then
        log_warn "Default profile SOUL.md not found at $source; skipping"
        return 0
    fi

    multi_target_dir="$HERMES_HOME/profiles/default"
    multi_target="$multi_target_dir/SOUL.md"
    single_target="$HERMES_HOME/SOUL.md"

    if [ -d "$HERMES_HOME/profiles" ]; then
        # Multi-profile layout — write to profiles/default/SOUL.md only
        mkdir -p "$multi_target_dir"
        if cp "$source" "$multi_target" 2>/dev/null; then
            log_success "Default profile SOUL.md installed at $multi_target"
        else
            log_warn "Could not install default profile SOUL.md to $multi_target"
        fi
    else
        # Single-profile layout — write to top-level SOUL.md only
        if cp "$source" "$single_target" 2>/dev/null; then
            log_success "Default profile SOUL.md installed at $single_target"
        else
            log_warn "Could not install default profile SOUL.md to $single_target"
        fi
    fi
}

# ============================================
# Install IT_ADMIN specialist Profile
# ============================================
# The IT_ADMIN profile lives at $INFRA_DIR/profiles/it_admin/ and copies
# SOUL.md + skills/*.md into $HERMES_HOME/profiles/it_admin/. IT_ADMIN
# requires multi-profile layout — auto-create $HERMES_HOME/profiles/ if
# absent. Backed by BACKLOG #20. Replaces the retired linux_admin +
# network_admin + windows_admin + vsphere_admin split (BACKLOG #16-19).

install_it_admin_profile_soul() {
    local source_dir="$INFRA_DIR/profiles/it_admin"
    local target_dir="$HERMES_HOME/profiles/it_admin"
    local copied=0

    if [ ! -d "$source_dir" ]; then
        log_warn "IT_ADMIN profile source dir not found at $source_dir; skipping"
        return 0
    fi

    # IT_ADMIN requires multi-profile layout; create profiles/ if absent
    if [ ! -d "$HERMES_HOME/profiles" ]; then
        log_info "Multi-profile layout not detected; creating $HERMES_HOME/profiles/"
        if ! mkdir -p "$HERMES_HOME/profiles" 2>/dev/null; then
            log_warn "Could not create $HERMES_HOME/profiles/; IT_ADMIN install skipped"
            return 0
        fi
    fi

    if ! mkdir -p "$target_dir" 2>/dev/null; then
        log_warn "Could not create $target_dir; IT_ADMIN install skipped"
        return 0
    fi

    # Copy SOUL.md
    if [ -f "$source_dir/SOUL.md" ]; then
        if cp "$source_dir/SOUL.md" "$target_dir/SOUL.md" 2>/dev/null; then
            log_success "IT_ADMIN SOUL.md installed at $target_dir/SOUL.md"
            copied=$((copied + 1))
        else
            log_warn "Could not install $target_dir/SOUL.md"
        fi
    else
        log_warn "IT_ADMIN SOUL.md not found at $source_dir/SOUL.md; skipping"
    fi

    # Copy all skill files from skills/*.md
    if [ -d "$source_dir/skills" ]; then
        mkdir -p "$target_dir/skills"
        local skill_count=0
        local skill_file
        for skill_file in "$source_dir/skills/"*.md; do
            if [ -f "$skill_file" ]; then
                local skill_name
                skill_name=$(basename "$skill_file")
                if cp "$skill_file" "$target_dir/skills/$skill_name" 2>/dev/null; then
                    skill_count=$((skill_count + 1))
                else
                    log_warn "Could not install $target_dir/skills/$skill_name"
                fi
            fi
        done
        if [ "$skill_count" -gt 0 ]; then
            log_success "IT_ADMIN $skill_count skill file(s) installed at $target_dir/skills/"
            copied=$((copied + 1))
        fi
    else
        log_warn "IT_ADMIN skills/ directory not found at $source_dir/skills; skipping"
    fi

    if [ "$copied" -gt 0 ]; then
        log_success "IT_ADMIN profile installed ($copied set(s) of files)"
    fi

    # Inherit provider/model/base_url from default profile so IT_ADMIN
    # uses the same LLM as default. Same pattern as the retired
    # install_linux_admin_profile_soul().
    local default_config="$HERMES_HOME/config.yaml"
    local it_admin_config="$target_dir/config.yaml"
    local default_model default_provider default_base_url

    if [ ! -f "$default_config" ]; then
        log_warn "Default profile config.yaml not found at $default_config; IT_ADMIN will use runtime defaults"
        return 0
    fi

    # Extract model.default, model.provider, model.base_url via awk (handles
    # YAML's nested structure). Falls back to empty string if missing.
    default_model=$(awk '/^model:/{flag=1; next} flag && /^  default:/{print $2; exit}' "$default_config")
    default_provider=$(awk '/^model:/{flag=1; next} flag && /^  provider:/{print $2; exit}' "$default_config")
    default_base_url=$(awk '/^model:/{flag=1; next} flag && /^  base_url:/{print $2; exit}' "$default_config")

    if [ -z "$default_model" ] && [ -z "$default_provider" ]; then
        log_warn "Could not extract model.* from default config.yaml; IT_ADMIN will use runtime defaults"
        return 0
    fi

    # Write IT_ADMIN config.yaml. Only include the fields we extracted —
    # leave the rest of the config (terminal, browser, etc.) to runtime
    # defaults so the profile stays minimal.
    cat > "$it_admin_config" <<EOF
# IT_ADMIN profile config
# Inherited from default profile (model.default, model.provider, model.base_url)
# on $(date -u +%Y-%m-%dT%H:%M:%SZ)
model:
  default: ${default_model}
  provider: ${default_provider}
  base_url: ${default_base_url}
EOF

    log_success "IT_ADMIN config.yaml written with provider=$default_provider model=$default_model"
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
# Generate Hermes Dashboard credentials
# ============================================
# Writes dashboard.basic_auth.username/password/secret into
# ~/.hermes/config.yaml so the basic plugin registers and the auth gate
# is satisfied for the non-loopback bind in install_hermes_dashboard_service.
# Credentials are also saved to /var/log/hermes-bootstrap-credentials.log
# (mode 0600, owned by $HERMES_USER) for the customer to retrieve later —
# they're never stored in plaintext on disk anywhere else.

generate_dashboard_credentials() {
    local dashboard_user="${DASHBOARD_USER:-admin}"
    local dashboard_password dashboard_secret credentials_log
    local hermes_bin config_path

    hermes_bin="$HERMES_HOME/hermes-agent/venv/bin/hermes"
    config_path="$HERMES_HOME/config.yaml"
    credentials_log="/var/log/hermes-bootstrap-credentials.log"

    log_info "Generating Hermes Dashboard credentials for user '$dashboard_user'..."

    # Generate 20-char alphanumeric password (URL-safe-ish, no special chars
    # so it survives bash quoting and config.yaml escaping).
    dashboard_password="$(openssl rand -base64 24 | tr -d '=+/' | cut -c1-20)"
    # Generate 32-byte hex secret for session signing.
    dashboard_secret="$(openssl rand -hex 32)"

    # Persist into config.yaml via the Hermes CLI so we don't have to hand-
    # edit YAML (which risks indentation breakage). The basic plugin reads
    # dashboard.basic_auth.{username,password,secret} from config.yaml on
    # dashboard startup; it hashes the plaintext password in-memory at load
    # time (see plugins/dashboard_auth/basic/register() in hermes-agent).
    if [ ! -x "$hermes_bin" ]; then
        log_error "hermes binary not found at $hermes_bin; cannot write dashboard credentials"
        return 1
    fi

    "$hermes_bin" config set dashboard.basic_auth.username "$dashboard_user" > /dev/null 2>&1 || \
        { log_error "Could not set dashboard.basic_auth.username"; return 1; }
    "$hermes_bin" config set dashboard.basic_auth.password "$dashboard_password" > /dev/null 2>&1 || \
        { log_error "Could not set dashboard.basic_auth.password"; return 1; }
    "$hermes_bin" config set dashboard.basic_auth.secret "$dashboard_secret" > /dev/null 2>&1 || \
        { log_error "Could not set dashboard.basic_auth.secret"; return 1; }

    log_success "Dashboard credentials written to $config_path (basic plugin will register on next dashboard start)"

    # Save the plaintext credentials to a 0600 log so the customer can
    # retrieve them later. /var/log is more durable than $HERMES_HOME (a
    # customer rebuilding their user account leaves /var/log intact).
    sudo install -m 0600 -o "$HERMES_USER" /dev/null "$credentials_log" 2>/dev/null || \
        sudo touch "$credentials_log" && sudo chown "$HERMES_USER" "$credentials_log" && sudo chmod 0600 "$credentials_log"
    cat >> "$credentials_log" <<EOF
# Hermes Dashboard credentials
# Generated by bootstrap.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Save these — they are not stored in plaintext anywhere else.
URL:      http://$(hostname -I | awk '{print $1}'):$HERMES_PORT
Username: $dashboard_user
Password: $dashboard_password
EOF
    sudo chown "$HERMES_USER" "$credentials_log" 2>/dev/null || true
    sudo chmod 0600 "$credentials_log" 2>/dev/null || true

    echo ""
    echo "============================================"
    echo "  HERMES DASHBOARD CREDENTIALS"
    echo "  (saved to $credentials_log, mode 0600)"
    echo "============================================"
    echo "  URL:      http://$(hostname -I | awk '{print $1}'):$HERMES_PORT"
    echo "  Username: $dashboard_user"
    echo "  Password: $dashboard_password"
    echo "============================================"
    echo ""

    # Export so downstream functions can reuse if needed (currently informational).
    export DASHBOARD_PASSWORD="$dashboard_password"
    export DASHBOARD_SECRET="$dashboard_secret"
}

# ============================================
# Install Hermes Dashboard systemd service
# ============================================
# Writes a unit file so the dashboard survives reboots and is supervised by
# systemd. Skipped silently on systems without systemd (e.g. containers).
# The unit reuses the same nohup command as before so behaviour is identical.

install_hermes_dashboard_service() {
    # Detect systemd; bail out quietly on non-systemd systems.
    if [ ! -d /run/systemd/system ] && [ ! -d /etc/systemd/system ]; then
        log_info "systemd not detected; skipping dashboard service install"
        return 0
    fi
    if ! command -v systemctl > /dev/null 2>&1; then
        log_info "systemctl not available; skipping dashboard service install"
        return 0
    fi

    local unit_file="/etc/systemd/system/hermes-dashboard.service"
    local hermes_user="${HERMES_USER:-$USER}"
    local hermes_bin="$HERMES_HOME/hermes-agent/venv/bin/hermes"
    local dashboard_log="$HERMES_HOME/logs/dashboard.log"

    # Ensure log dir exists with correct ownership before writing the unit.
    mkdir -p "$HERMES_HOME/logs"

    # /etc/systemd/system/ is root-owned. bootstrap.sh runs as the install user,
    # so every privileged op needs sudo. cat <<EOF | sudo tee > /dev/null writes
    # the unit and then truncates stdout so we don't contaminate $(...) captures.
    sudo tee "$unit_file" > /dev/null <<EOF
[Unit]
Description=Hermes Agent Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$hermes_user
WorkingDirectory=$HERMES_HOME/hermes-agent
ExecStart=$hermes_bin dashboard --port $HERMES_PORT --host 0.0.0.0 --skip-build
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable hermes-dashboard.service > /dev/null 2>&1 || true
    log_success "Installed systemd unit: hermes-dashboard.service"
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

    # Prefer systemd (auto-restarts on reboot/crash). Fall back to nohup
    # for non-systemd hosts (containers, minimal VMs).
    if command -v systemctl > /dev/null 2>&1 && sudo test -f /etc/systemd/system/hermes-dashboard.service; then
        log_info "Starting via systemd: hermes-dashboard.service"
        sudo systemctl start hermes-dashboard.service
    else
        log_info "Starting via nohup (systemd not available)"
        mkdir -p "$HERMES_HOME/logs"
        (cd "$HERMES_HOME/hermes-agent" && \
            source venv/bin/activate && \
            nohup hermes dashboard --port "$HERMES_PORT" --host 0.0.0.0 --skip-build \
                > "$HERMES_HOME/logs/dashboard.log" 2>&1 &)
    fi

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

    # Check if service account + token already exist (idempotent re-runs).
    # The env var name is GRAFANA_SERVICE_ACCOUNT_TOKEN (no _MCP_) because
    # that's what the grafana/mcp-grafana binary actually reads.
    if [ -f "$secrets_file" ] && grep -q "^GRAFANA_SERVICE_ACCOUNT_TOKEN=glsa_" "$secrets_file" 2>/dev/null; then
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

    # Persist token to secrets file. The env var name is
    # GRAFANA_SERVICE_ACCOUNT_TOKEN (no _MCP_) because grafana/mcp-grafana
    # reads that exact var from its environment.
    mkdir -p "$secrets_dir"
    cat > "$secrets_file" <<EOF
# Grafana MCP service account token
# Generated by bootstrap.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# Service Account: aiamsbs-mcp (id: ${sa_id})
# Source: ${grafana_url}/admin/serviceaccounts
GRAFANA_SERVICE_ACCOUNT_TOKEN=${token}
EOF
    chmod 600 "$secrets_file"

    log_success "Grafana service account created (id=${sa_id}); token saved to $secrets_file"
}

# ============================================
# Deploy MCP Stack (grafana-mcp)
# ============================================

deploy_mcp_stack() {
    # INFRA_DIR is set once in main() upfront; this function should not re-clone.
    local infra_dir="${INFRA_DIR:?INFRA_DIR not set — main() must clone repo first}"
    local mcp_compose="$infra_dir/docker-compose.mcp.yml"

    if [ ! -f "$mcp_compose" ]; then
        log_warn "MCP compose file not found at $mcp_compose; skipping"
        return 0
    fi

    if [ ! -f "$HERMES_HOME/secrets/grafana-mcp.env" ]; then
        log_warn "grafana-mcp.env not found at $HERMES_HOME/secrets/; skipping"
        return 0
    fi

    # Write a .env file next to the compose so the compose can reference
    # ${HERMES_SECRETS_DIR} without hardcoding /home/ansible. This keeps the
    # compose portable across users and $HERMES_HOME values.
    local mcp_env_file="$infra_dir/.env.mcp"
    log_info "Writing MCP compose .env (HERMES_SECRETS_DIR=$HERMES_HOME/secrets)..."
    cat > "$mcp_env_file" <<EOF
HERMES_SECRETS_DIR=$HERMES_HOME/secrets
EOF

    log_info "Deploying MCP stack..."

    # sg docker -c sidesteps the docker-group-not-applied-yet issue that
    # hits the first docker command run in a fresh SSH session after
    # install_docker (usermod -aG docker only takes effect on next login).
    if sg docker -c "docker compose --env-file '$mcp_env_file' -f '$mcp_compose' up -d" 2>&1 | tail -5; then
        log_success "MCP stack deployed (grafana-mcp on port 8000)"
    else
        log_warn "MCP stack deployment failed; continuing"
        return 0
    fi
}

# ============================================
# Deploy Inventory Stack (inventory-mcp + nmap-discovery)
# ============================================

deploy_inventory_stack() {
    # INFRA_DIR is set once in main() upfront.
    local infra_dir="${INFRA_DIR:?INFRA_DIR not set — main() must clone repo first}"
    local inv_dir="$infra_dir/inventory-stack"
    local inv_compose="$inv_dir/docker-compose.yml"

    if [ ! -f "$inv_compose" ]; then
        log_warn "inventory-stack/docker-compose.yml not found at $inv_compose; skipping"
        return 0
    fi

    log_info "Deploying inventory stack..."

    # sg docker -c sidesteps the docker-group-not-applied-yet issue.
    # Note: only inventory-mcp starts here. nmap-discovery is in the
    # 'discovery' profile and is started separately by start_nmap_discovery()
    # below — see that function for why.
    if sg docker -c "docker compose -f '$inv_compose' up -d" 2>&1 | tail -10; then
        log_success "Inventory stack deployed (inventory-mcp on port 8001)"
    else
        log_warn "Inventory stack deployment failed; continuing"
        return 0
    fi
}

# register_inventory_mcp [profile_name]
# Registers the inventory-mcp MCP server in a Hermes profile's config.yaml.
# Default: 'default' profile (the interim coordinator for AIAMSBS).
#
# Hermes config layout auto-detection:
#   - Multi-profile (workstation dev): ~/.hermes/profiles/<name>/config.yaml
#   - Single-profile (AIAMSBS customer VM): ~/.hermes/config.yaml
# This function writes to whichever location exists, preferring multi-profile
# when the profiles/ dir is present (the dev path) and falling back to
# ~/.hermes/config.yaml for the single-profile customer deploy.
#
# Idempotent — skips if already registered.
register_inventory_mcp() {
    local profile="${1:-default}"
    local config_path

    # Multi-profile layout: ~/.hermes/profiles/<name>/config.yaml
    if [ -d "$HOME/.hermes/profiles" ]; then
        config_path="$HOME/.hermes/profiles/${profile}/config.yaml"
    # Single-profile layout (AIAMSBS customer VM): ~/.hermes/config.yaml
    elif [ -f "$HOME/.hermes/config.yaml" ] || [ -d "$HOME/.hermes" ]; then
        config_path="$HOME/.hermes/config.yaml"
        profile="default"  # ignore profile arg in single-profile mode
    else
        log_error "No Hermes config found at ~/.hermes/ — run bootstrap.sh first?"
        return 1
    fi

    log_info "Registering inventory-mcp in profile '$profile' (config: $config_path)..."

    if [ ! -d "$(dirname "$config_path")" ]; then
        log_warn "Profile dir not found at $(dirname "$config_path") — creating"
        mkdir -p "$(dirname "$config_path")"
    fi

    if [ ! -f "$config_path" ]; then
        log_warn "Profile config not found at $config_path — creating empty config"
        touch "$config_path"
        chmod 600 "$config_path"
    fi

    # Idempotent: skip if already registered
    if grep -q 'name: inventory-mcp' "$config_path" 2>/dev/null; then
        log_success "inventory-mcp already registered in profile '$profile'"
        return 0
    fi

    # Backup + append
    cp "$config_path" "${config_path}.bak"
    cat >> "$config_path" << 'EOF'

mcp_servers:
  - name: inventory-mcp
    url: http://localhost:8001/mcp
    transport: streamable-http
EOF

    chmod 600 "$config_path"
    log_success "inventory-mcp registered in profile '$profile'"
}

# install_inventory_discovery_skill
# Copies the inventory-discovery skill (shipped in inventory-stack/) into
# ~/.hermes/skills/inventory-discovery so Hermes can route "inventory X"
# prompts through the discover.py workflow. Idempotent — overwrites on each
# bootstrap run so skill updates ship automatically.
install_inventory_discovery_skill() {
    local infra_dir="${INFRA_DIR:?INFRA_DIR not set — main() must clone repo first}"
    local src="$infra_dir/inventory-stack/inventory-discovery"
    local dst="$HOME/.hermes/skills/inventory-discovery"

    if [ ! -d "$src" ]; then
        log_warn "inventory-discovery skill source not found at $src; skipping"
        return 0
    fi

    log_info "Installing inventory-discovery skill to $dst..."
    mkdir -p "$dst/scripts"

    # Copy SKILL.md + scripts (overwrite so updates ship automatically)
    cp "$src/SKILL.md" "$dst/SKILL.md"
    cp "$src/scripts/discover.py" "$dst/scripts/discover.py"
    chmod +x "$dst/scripts/discover.py"

    # Lock down perms (skill files shouldn't be world-readable)
    chmod -R u+rwX,go-rwx "$dst"

    log_success "inventory-discovery skill installed (trigger: 'inventory the subnet ...')"
}

# start_nmap_discovery
# Starts the nmap-discovery container in the 'discovery' compose profile.
# Idempotent — skips if already running. Requires NET_RAW + NET_ADMIN caps,
# which is why it's opt-in via a separate profile rather than started by
# deploy_inventory_stack() by default.
start_nmap_discovery() {
    local infra_dir="${INFRA_DIR:?INFRA_DIR not set — main() must clone repo first}"
    local inv_dir="$infra_dir/inventory-stack"
    local inv_compose="$inv_dir/docker-compose.yml"

    if [ ! -f "$inv_compose" ]; then
        log_warn "inventory-stack/docker-compose.yml not found; skipping nmap-discovery"
        return 0
    fi

    # Idempotent: skip if already running
    if command -v docker &> /dev/null && sg docker -c "docker ps --format '{{.Names}}'" 2>/dev/null | grep -q '^nmap-discovery$'; then
        log_success "nmap-discovery already running"
        return 0
    fi

    log_info "Starting nmap-discovery (compose profile 'discovery', requires NET_RAW + NET_ADMIN)..."
    if sg docker -c "docker compose -f '$inv_compose' --profile discovery up -d nmap-discovery" 2>&1 | tail -10; then
        log_success "nmap-discovery started on port 8002 (host-network mode)"
    else
        log_warn "nmap-discovery failed to start; continuing (inventory-mcp still works for CRUD)"
        return 0  # don't fail bootstrap on this
    fi
}

# ============================================
# Auto-Deploy Stack
# ============================================

auto_deploy_stack() {
    log_info "Starting auto-deploy of monitoring stack..."

    # INFRA_DIR is set once in main() upfront.
    local infra_dir="${INFRA_DIR:?INFRA_DIR not set — main() must clone repo first}"

    # Config-as-code: deploy directly from docker-compose.yml.
    # No LLM in the deploy path — the compose file is the single source of truth.
    # Running an agent here previously caused it to "fix" prose-vs-config drift
    # by editing docker-compose.yml on the VM to match hallucinated service lists.
    if [ ! -f "$infra_dir/docker-compose.yml" ]; then
        log_error "docker-compose.yml not found at $infra_dir"
        log_info "Run: cd $infra_dir && docker compose up -d"
        return 1
    fi

    cd "$infra_dir" || return 1

    # Pull images first so a slow mirror doesn't time out the up.
    # sg docker -c sidesteps the docker-group-not-applied-yet issue that
    # hits the first docker command run in a fresh SSH session after
    # install_docker (usermod -aG docker only takes effect on next login).
    if sg docker -c "docker compose pull" 2>&1 | tee /tmp/aiamsbs_pull.log | tail -5; then
        log_success "Images pulled"
    else
        log_warn "Some images failed to pull; continuing with local cache"
    fi

    if sg docker -c "docker compose up -d" 2>&1 | tee /tmp/aiamsbs_up.log; then
        log_success "Stack deployed successfully!"
        log_info "Containers:"
        sg docker -c "docker compose ps --format '  {{.Names}}\\t{{.Status}}\\t{{.Ports}}'" || true
    else
        log_error "Stack deployment failed. Retry manually with:"
        log_info "  cd $infra_dir && docker compose up -d"
        return 1
    fi
}
# ============================================
# Verify Installation
# ============================================

# verify_service_health <name> <url> <expected_status>
# Returns 0 if the URL responds with one of the expected HTTP statuses, else 1.
# Treats 302 as success for the Hermes Dashboard (auth gate redirects).
# <expected_status> may be a single code ("200") or pipe-separated list ("200|406").
# Normalizes curl's behavior on SSE/timeout responses (which can produce a
# code that's not exactly 3 digits) to "000".
verify_service_health() {
    local name="$1"
    local url="$2"
    local expected="${3:-200}"
    local code matched c

    code=$(curl -s -o /dev/null --max-time 5 --connect-timeout 3 -w '%{http_code}' "$url" 2>/dev/null)
    # Normalize non-3-digit responses (SSE streams can produce "200" + later
    # timeout-concatenated codes) to "000" so the comparison is meaningful.
    if ! [[ "$code" =~ ^[0-9]{3}$ ]]; then
        code="000"
    fi

    matched=false
    IFS='|' read -ra expected_codes <<< "$expected"
    for c in "${expected_codes[@]}"; do
        if [ "$code" = "$c" ]; then
            matched=true
            break
        fi
    done

    if $matched; then
        if [ "$code" = "302" ] && [ "$name" = "Hermes Dashboard" ]; then
            log_success "  ✓ $name: HTTP $code (auth gate active)"
        else
            log_success "  ✓ $name: HTTP $code"
        fi
        return 0
    else
        log_error "  ✗ $name: HTTP $code (expected $expected)"
        return 1
    fi
}

# list_listening_ports
# Prints the bind address + scope for every known AIAMSBS port that's
# currently listening. Reads ss(8) output — does not require docker access.
list_listening_ports() {
    local line addr port scope
    while read -r line; do
        # Skip empty lines and headers
        [ -z "$line" ] && continue
        addr=$(echo "$line" | awk '{print $4}')
        [ -z "$addr" ] && continue
        # Extract port (last colon-separated field, strip trailing ] for IPv6)
        port="${addr##*:}"
        port="${port%]}"
        # Filter to known AIAMSBS ports
        case "$port" in
            514|1514|3000|3100|8000|8001|8002|9090|9119|12345) ;;
            *) continue ;;
        esac
        # Determine scope (public vs localhost-only)
        case "$addr" in
            0.0.0.0:*|"[::]":*) scope="public" ;;
            127.0.0.1:*|"[::1]":*) scope="localhost-only" ;;
            *) scope="other" ;;
        esac
        printf "    %-5s  %-30s  %s\n" "$port" "$addr" "$scope"
    done < <(ss -tlnH 2>/dev/null) | sort -u
}

# print_access_summary
# Prints the customer-facing "Bootstrap Complete!" banner with URLs,
# credentials, listening ports, and a verification hint.
# Reads dashboard creds from /var/log/hermes-bootstrap-credentials.log
# and Grafana creds from $INFRA_DIR/.env (falls back to defaults).
print_access_summary() {
    local host_ip dash_user dash_pass grafana_user grafana_pass gp
    host_ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    [ -z "$host_ip" ] && host_ip="localhost"

    dash_user=""
    dash_pass=""
    if [ -f /var/log/hermes-bootstrap-credentials.log ]; then
        dash_user=$(grep '^Username:' /var/log/hermes-bootstrap-credentials.log 2>/dev/null | awk '{print $2}')
        dash_pass=$(grep '^Password:' /var/log/hermes-bootstrap-credentials.log 2>/dev/null | awk '{print $2}')
    fi

    grafana_user="admin"
    grafana_pass="admin123"  # docker-compose default fallback
    if [ -n "$INFRA_DIR" ] && [ -f "$INFRA_DIR/.env" ]; then
        gp=$(grep '^GRAFANA_PASSWORD=' "$INFRA_DIR/.env" 2>/dev/null | cut -d= -f2-)
        [ -n "$gp" ] && grafana_pass="$gp"
    fi

    echo ""
    echo "============================================"
    echo "  Bootstrap Complete!"
    echo "============================================"
    echo ""
    echo "  Access your AIAMSBS host (http://$host_ip):"
    echo ""
    echo "  📊 Grafana (visualization)"
    echo "     URL:      http://$host_ip:3000"
    echo "     Username: $grafana_user"
    echo "     Password: $grafana_pass"
    echo ""
    echo "  🔒 Hermes Dashboard (chat UI + Agent)"
    echo "     URL:      http://$host_ip:$HERMES_PORT"
    echo "     Username: ${dash_user:-admin}"
    echo "     Password: ${dash_pass:-<not generated yet>}"
    echo ""
    echo "  📈 Monitoring (no auth required)"
    echo "     Prometheus:    http://$host_ip:9090"
    echo "     Loki:          http://$host_ip:3100"
    echo "     Alloy UI:      http://$host_ip:12345"
    echo ""
    echo "  🔧 MCP servers (localhost-only by default)"
    echo "     Inventory MCP: http://localhost:8001/mcp"
    echo "     Grafana MCP:   http://localhost:8000/mcp"
    echo ""
    echo "  📝 Verify the LLM is working:"
    echo "     hermes chat -q \"hello!\""
    echo ""
    echo "  🔒 To restrict port $HERMES_PORT to specific IPs:"
    echo "     sudo ufw allow from <your-ip> to any port $HERMES_PORT"
    echo "     sudo ufw enable"
    echo "============================================"
    echo ""
}

verify_installation() {
    log_info "Verifying installation..."
    local errors=0

    # Tool checks
    if ! command -v docker &> /dev/null; then
        log_error "Docker not found"
        errors=$((errors + 1))
    else
        log_success "Docker: $(docker --version)"
    fi

    if docker compose version &> /dev/null 2>&1 || command -v docker-compose &> /dev/null; then
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

    # LLM plumbing smoke test — confirms the API key + provider + model all
    # work end-to-end. A passing "hello!" means Hermes can talk to the LLM.
    if command -v hermes &>/dev/null || [ -x "$HERMES_HOME/hermes-agent/venv/bin/hermes" ]; then
        log_info "LLM smoke test (hermes chat -q \"hello!\")..."
        local hermes_bin="$HERMES_HOME/hermes-agent/venv/bin/hermes"
        [ ! -x "$hermes_bin" ] && hermes_bin="$(command -v hermes)"
        local hello_response
        hello_response=$(timeout 30 "$hermes_bin" chat -q "hello!" 2>&1 | head -c 200 || true)
        if [ -n "$hello_response" ] && ! echo "$hello_response" | grep -qiE 'error|exception|401|unauthorized|api key'; then
            log_success "  ✓ LLM responds to \"hello!\""
        else
            log_warn "  ! LLM smoke test inconclusive (response: ${hello_response:0:80})"
        fi
    fi

    # Service health checks — only if docker compose is actually running
    if command -v docker &> /dev/null && sg docker -c 'docker ps --format "{{.Names}}"' &>/dev/null; then
        log_info "Checking service health..."
        verify_service_health "Prometheus"      "http://localhost:9090/-/ready"            "200"    || errors=$((errors+1))
        verify_service_health "Loki"            "http://localhost:3100/ready"              "200"    || errors=$((errors+1))
        verify_service_health "Grafana"         "http://localhost:3000/api/health"         "200"    || errors=$((errors+1))
        verify_service_health "Alloy"           "http://localhost:12345/-/ready"           "200"    || errors=$((errors+1))
        # MCP servers return 406 (Not Acceptable) to a bare GET because they
        # expect Accept: text/event-stream + a POST with initialize. 200 means
        # the SSE stream opened; 406 means the endpoint exists. Either is OK.
        verify_service_health "Inventory MCP"   "http://localhost:8001/mcp"                "200|406" || errors=$((errors+1))
        verify_service_health "Grafana MCP"     "http://localhost:8000/mcp"                "200|406" || errors=$((errors+1))
        verify_service_health "Hermes Dashboard" "http://localhost:$HERMES_PORT/"          "302"    || errors=$((errors+1))

        log_info "Listening ports (AIAMSBS services):"
        list_listening_ports || true
    else
        log_warn "Docker not running; skipping service health checks"
    fi

    if [ $errors -eq 0 ]; then
        log_success "All checks passed!"
    else
        log_warn "$errors check(s) failed"
    fi

    return $errors
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

    # Clone the infrastructure repo once, upfront, before anything else needs it.
    # This guarantees $INFRA_DIR is set for every downstream function regardless
    # of the order they're called in. Functions below should use $INFRA_DIR
    # directly rather than re-calling clone_infra_repo().
    INFRA_DIR="$(clone_infra_repo)"
    export INFRA_DIR

    configure_hermes_api
    install_default_profile_soul
    if [ "$INSTALL_IT_ADMIN" = true ]; then
        install_it_admin_profile_soul
    fi
    build_dashboard_ui
    generate_dashboard_credentials
    install_hermes_dashboard_service
    start_hermes_dashboard

    if [ "$AUTO_DEPLOY" = true ]; then
        auto_deploy_stack
    else
        log_info "Skipping auto-deploy (--no-auto-deploy)"
        log_info "To deploy manually, run:"
        log_info "  cd ~/AIAMSBS && docker compose up -d"
    fi

    # Post-install steps: skills install, MCP service account, MCP deploy
    install_grafana_skills
    create_grafana_mcp_service_account
    deploy_mcp_stack
    deploy_inventory_stack

    # Wire inventory-mcp into the default Hermes profile + start nmap-discovery
    # so a customer can immediately ask Hermes to discover/inventory their
    # network without re-running register_inventory_mcp.sh by hand.
    register_inventory_mcp "default"
    install_inventory_discovery_skill
    start_nmap_discovery

    # Print customer-facing access summary (URLs, credentials, ports, hints)
    print_access_summary

    verify_installation
}

main "$@"