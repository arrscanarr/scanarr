## Scanarr

A tool for searching files and folders against tracker APIs and reporting which ones are not found on the tracker.
To use it, you must have a configured **Jackett** instance. Other tools like Prowlarr or the use of Torznab is currently not supported.

### Installation

#### Using Docker
You can use the pre-built Docker image or build your own:

**Pull from GitHub Container Registry:**
```bash
docker pull ghcr.io/arrscanarr/scanarr:latest
```

**Build locally:**
```bash
git clone https://github.com/arrscanarr/scanarr.git
cd scanarr
docker build -t scanarr .
```

#### Local Installation (venv)
```bash
git clone https://github.com/arrscanarr/scanarr.git
cd scanarr
python3 -m venv venv
source venv/bin/activate
pip install .
```

### Usage

**Docker:**
```bash
docker run --rm scanarr --help
```

**Local:**
```bash
scanarr --help
```

or

```bash
python -m scanarr.main --help
```

**Example:**
```bash
docker run --rm -t -v /path/to/downloads:/data:ro ghcr.io/arrscanarr/scanarr:latest /data --api-url http://x.x.x.x:9117 --api-key xxxx --tracker tracker-name --delay 2 --exclude-groups ThisBadGroup SHiT LowBitrateGroup BadEncodeGroup
```

Obtaining tracker name from Jackett:
Click on the search icon of a tracker. Look in the URL for `tracker=`

### Development
For development, install with editable mode:
```bash
pip install -e .
```
