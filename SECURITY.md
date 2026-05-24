# Security Policy

## Reporting Vulnerabilities

If you find a security vulnerability in this project, please report it responsibly. Do not open a public issue — instead, contact the maintainer directly.

---

## Security Best Practices

### Before Running the Bootstrap

1. **Review the script** — Always read `bootstrap.sh` before running it on your system:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/rylanddufour/AIAMSBS/main/bootstrap.sh | less
   ```

2. **Understand what it does** — The script installs:
   - Docker and Docker Compose
   - Hermes Agent
   - MCP servers (optional)
   - Custom skills

3. **Run as non-root** — The script warns against running as root. Use a regular user with sudo access.

### Secrets and Credentials

**Never hardcode secrets in this repo.**

- API tokens, passwords, and keys should be set via environment variables
- After deployment, edit the `.env` file in `mcp-servers/`
- Use read-only tokens where possible (especially for GitHub MCP)

Example:
```bash
# Set environment variables before running
export GITHUB_PERSONAL_ACCESS_TOKEN=ghp_xxxx
export POSTGRES_MCP_DATABASE_URI=postgresql://user:pass@host:5432/db
```

### MCP Servers

- MCP servers run inside Docker containers with limited permissions
- Only enable the MCP servers you need
- Review the docker-compose file and restrict network access as needed
- Do not expose MCP servers to the public internet without authentication

### SSH Access

- The bootstrap expects SSH key-based authentication
- Keep your private keys secure and never commit them to version control
- Use dedicated deploy keys or machine-specific keys

---

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.x     | ✅ Current |

---

## Contact

For security concerns, please contact the repository maintainer directly. Do not post security issues in public issues or discussions.