# Bitwarden MCP server image — stdio transport, talks to vaultwarden
# over BW_API_BASE_URL/BW_IDENTITY_URL.
#
# BACKLOG #49 — bitwarden/mcp-server container.
#
# Why a custom image instead of using bitwarden/mcp-server's published
# npm package directly via host npm: so the AIAMSBS host doesn't need
# Node.js, npm, or the @bitwarden/cli on the host filesystem. Everything
# lives inside this container; the host only needs `docker`.
#
# Note on the bitwarden/mcp-server README warning ("never deploy to
# containers, cloud hosting, or public servers"): that warning is in the
# same bullet list as "never share MCP config files" and "never use over
# untrusted networks" — it's about EXPOSURE, not containerization. We
# run with NO published ports (stdio only), so the vault contents never
# leave the host via the network.

FROM node:22-bookworm-slim

# wget is needed by the launch script's health check; ca-certificates so
# HTTPS calls to the BW_*_URLs work out of the box.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates wget \
    && rm -rf /var/lib/apt/lists/*

# Install both @bitwarden/cli (`bw`) and @bitwarden/mcp-server
# (`mcp-server-bitwarden`). The MCP server shells out to `bw`, so both
# need to be on the same global prefix so they're both on PATH.
RUN npm install -g @bitwarden/cli @bitwarden/mcp-server

# Persistent dir for the bw CLI's session cache + our saved BW_SESSION.
# Mounted as a named volume in docker-compose so logins survive restarts.
RUN mkdir -p /var/lib/bitwarden-cli && chown node:node /var/lib/bitwarden-cli
USER node
WORKDIR /home/node

# Launch wrapper handles login+unlock+session persistence before exec'ing
# the actual MCP server. See launch-bitwarden-mcp.sh for the flow.
COPY launch-bitwarden-mcp.sh /usr/local/bin/launch-bitwarden-mcp.sh
RUN chmod +x /usr/local/bin/launch-bitwarden-mcp.sh

ENTRYPOINT ["/usr/local/bin/launch-bitwarden-mcp.sh"]
CMD ["--stdio"]
