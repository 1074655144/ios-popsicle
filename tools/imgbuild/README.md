# iOS root image build (computer-side, reusable)

This builds the HFS+ root image that XNU mounts as `rd=ufsroot0`. It uses only
files from **your own IPSW** and runs entirely on Linux/WSL; no phone partition
is written.

## 1. Discover build-specific asset names

Do not hard-code cryptex DMG names for a new iOS build:

```bash
python3 tools/port/discover_ipsw_assets.py /path/to/IPSW \
  --verify-sha256 <official-sha256> \
  -o device/<codename>/ipsw_assets.env
```

The generated env file contains `CRYPTEX_DMGS` and `TRUSTCACHE_FILES` and is
local-only (`device/*` is ignored). Extract the three cryptex DMGs into one
directory (for example `/opt/work/ipsw`).

## 2. Install host tools

On Debian/Ubuntu/WSL:

```bash
sudo apt-get install rsync libguestfs-tools hfsprogs fuse
# Build apfs-fuse from your own checkout; set APFS=/path/to/apfs-fuse.
```

`mkfs.hfsplus -s` creates a **non-journaled** HFS+ volume: the Linux hfsplus
driver mounts journaled HFS+ read-only.

## 3. Build

Using the discovered env:

```bash
sudo env APFS=/opt/work/tools/apfs-fuse-src/build/apfs-fuse \
  IPSW_DIR=/opt/work/ipsw \
  IPSW_ASSETS=device/<codename>/ipsw_assets.env \
  OUT=/opt/work/iosroot.img SIZE=16G \
  bash tools/imgbuild/build_root.sh
```

Or with explicit DMGs:

```bash
sudo bash tools/imgbuild/mkiosroot.sh \
  /opt/work/ipsw/<OS.dmg> /opt/work/ipsw/<SystemOS.dmg> /opt/work/ipsw/<AppOS.dmg> \
  /opt/work/iosroot.img 16G
```

The script:

1. mounts the three APFS DMGs with `apfs-fuse`;
2. rsyncs OS / SystemOS cryptex / AppOS cryptex into a local staging tree;
3. hardlinks the shared dyld cache and cryptex files;
4. creates log stores and a **plain binary plist** `systembag.kb`
   (bare `KeyBagKeys` text causes `FATAL KEYBAG ERROR` in keybagd);
5. applies `sweet-root-tweaks.py`;
6. tars the tree and `guestfish tar-in` into a non-journaled HFS+ image;
7. runs `fsck.hfsplus` and prints the final SHA-256.

The image itself is device runtime data: keep it outside the repo. It is
ignored by `*.img`.
