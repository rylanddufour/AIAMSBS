# Docker Management Skill

**Description:** Manage Docker containers, images, and troubleshoot container issues

**Triggers:** 
- "docker", "containers", "container"
- "list containers", "running containers"
- "stop container", "start container", "restart container"
- "docker logs", "container logs"
- "docker status", "container status"
- "docker images", "list images"
- "container health", "docker resource usage"

---

## Tools

### List Containers
List all Docker containers (running and stopped).

```bash
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}"
```

### List Running Containers
Show only running containers.

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}"
```

### Container Status
Get detailed status of a specific container.

```bash
docker inspect <container_name> --format '{{.State.Status}} | CPU: {{.CPUStats.CPUUsage.TotalUsage}} | Memory: {{.MemoryStats.Usage}}'
```

### Start Container
Start a stopped container.

```bash
docker start <container_name>
```

### Stop Container
Stop a running container gracefully (SIGTERM).

```bash
docker stop <container_name>
```

### Restart Container
Restart a container.

```bash
docker restart <container_name>
```

### View Container Logs
View logs from a container.

```bash
docker logs --tail 100 <container_name>
```

### Follow Container Logs
Stream logs in real-time.

```bash
docker logs -f <container_name>
```

### View Resource Usage
Show CPU, memory, network I/O for running containers.

```bash
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}"
```

### List Images
List all Docker images.

```bash
docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}"
```

### Remove Unused Images
Clean up dangling images.

```bash
docker image prune -a
```

### Docker System DF
Show Docker disk usage.

```bash
docker system df
```

---

## Common Questions

| User Asks | Response Action |
|-----------|-----------------|
| "Show me running containers" | Run `docker ps` |
| "Check logs for X" | Run `docker logs --tail 100 <container>` |
| "What's using memory?" | Run `docker stats --no-stream` |
| "Restart the container" | Run `docker restart <container>` |
| "Clean up images" | Run `docker image prune -a` |