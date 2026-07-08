# subconverter-docker

This is a minimized image to run subconverter via Docker with auto-built images from GitHub Container Registry (ghcr.io).

## Quick Start

```bash
docker run -d --restart=always -p 25500:25500 ghcr.io/<your-username>/subconverter:master
# then check its status
curl http://localhost:25500/version
# if you see `subconverter vx.x.x backend` then the container is up and running
```

## Run with Docker Compose

```yaml
version: '3'
services:
  subconverter:
    image: ghcr.io/<your-username>/subconverter:master
    container_name: subconverter
    ports:
      - "25500:25500"
    restart: always
    volumes:
      - /docker/subconverter/data:/base  # Mount local /docker/subconverter/data to container /base
```

## Update Configuration

If you want to update `pref` configuration inside the docker, you can use the following command:

```bash
# assume your configuration file name is `newpref.ini`
curl -F "data=@newpref.ini" http://localhost:25500/updateconf?type=form\&token=password
# you may want to change this token in your configuration file
```

## Custom Configuration

For those who want to use their own `pref` configuration and/or rules, snippets, profiles:

```dockerfile
FROM ghcr.io/<your-username>/subconverter:master
# assume your files are inside replacements/
# subconverter folder is located in /base/, which has the same structure as the base/ folder in the repository
COPY replacements/ /base/
# expose internal port
EXPOSE 25500
# notice that you still need to use '-p 25500:25500' when starting the docker to forward this port
```

Save the content above to a `Dockerfile`, then run:

```bash
# build with this Dockerfile and tag it subconverter-custom
docker build -t subconverter-custom .
# run the docker detached, forward internal port 25500 to host port 25500
docker run -d --restart=always -p 25500:25500 subconverter-custom
# then check its status
curl http://localhost:25500/version
# if you see `subconverter vx.x.x backend` then the container is up and running
```
