# Linux Binary Build Note

The `ai-agent` binary in this folder is **platform-specific**:
- It must be built on a Linux machine (or in a Linux container).
- A Windows-built PyInstaller binary **cannot run on Linux** and vice versa.

## Option A: Build on Linux host

```bash
cd ai_agent
pip install -r requirements.txt pyinstaller
pyinstaller ai_agent.spec --clean --noconfirm
cp -r dist/ai-agent/. package/linux/
chmod +x package/linux/ai-agent package/linux/*.sh
```

## Option B: Build via Docker (from Windows / macOS / any host with Docker)

```bash
docker run --rm -v "$PWD":/work -w /work/ai_agent python:3.11-slim bash -c "
  apt-get update &&
  apt-get install -y --no-install-recommends binutils patchelf libpython3-dev &&
  pip install --no-cache-dir -r requirements.txt pyinstaller &&
  pyinstaller ai_agent.spec --clean --noconfirm &&
  cp -r dist/ai-agent/. package/linux/ &&
  chmod +x package/linux/ai-agent package/linux/*.sh
"
```

## Option C: GitHub Actions (recommended, no local Linux needed)

Just push a `v*.*.*` tag:

```bash
git tag v1.0.0
git push origin v1.0.0
```

The workflow at `.github/workflows/release-build.yml` builds three
platforms (Windows / Linux / macOS) and publishes a GitHub Release
with the binaries attached.

## Verifying the binary

After obtaining `ai-agent`:

```bash
chmod +x ai-agent
./ai-agent           # start CLI
./run.sh             # or use the wrapper
```
