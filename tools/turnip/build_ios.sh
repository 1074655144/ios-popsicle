#!/bin/bash
# Cross-build Turnip (Mesa's freedreno Vulkan driver) with UniXNU's Darwin kernel backend for
# iOS 16 arm64, and tools/vktest against it. Runs on a macOS machine with Xcode (CI: turnip.yml).
#   tools/turnip/build_ios.sh MESA_DIR NATIVEADRENO_DIR OUT_DIR
# MESA_DIR: Mesa 85fda3b with UniXNU's patches applied (scripts/data/adreno-compiler-inputs.json
# order). NATIVEADRENO_DIR: holds NativeAdrenoABI.h (version 1, the ABI our user client speaks).
# Options follow UniXNU scripts/build-turnip-darwin.py --target ios, with iOS 16.0 as the minimum
# and no builtin shader pack (Turnip compiles its own shaders at run time).
# OUT_DIR gets libvulkan_freedreno.dylib (install name /usr/lib/libvulkan_freedreno.dylib) and
# vktest, both ad-hoc signed, and SHA256SUMS.
set -euo pipefail
MESA=$(cd "$1" && pwd); ABI=$(cd "$2" && pwd); OUT=$3
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd)
SDK=$(xcrun --sdk iphoneos --show-sdk-path)
CC=$(xcrun --sdk iphoneos --find clang); CXX=$(xcrun --sdk iphoneos --find clang++)
AR=$(xcrun --sdk iphoneos --find ar); STRIP=$(xcrun --sdk iphoneos --find strip)
# Meson probes endian.h on the macOS host (HAVE_ENDIAN_H=1), but the actual compile targets the
# iOS SDK, whose <endian.h> has no __BYTE_ORDER (Apple uses __DARWIN_BYTE_ORDER). That leaves
# u_endian.h's UTIL_ARCH_* macros undefined, which also drops the endian-dependent
# PIPE_FORMAT_RG88/GR88 aliases. arm64 is always little-endian, so define them explicitly.
# The flex-generated ir3_lexer.c has no config.h/dlfcn.h include, so Dl_info/dladdr need the
# header forced in. Apply compile-only flags here; link flags below stay untouched.
BASE_FLAGS="['-target', 'arm64-apple-ios16.0', '-isysroot', '$SDK', '-fstack-protector-strong']"
CC_FLAGS="['-target', 'arm64-apple-ios16.0', '-isysroot', '$SDK', '-fstack-protector-strong', '-include', 'dlfcn.h', '-DUTIL_ARCH_LITTLE_ENDIAN=1', '-DUTIL_ARCH_BIG_ENDIAN=0']"
# tu_device_get_cache_uuid() -> tu_device_get_build_id() reads the ELF .note.gnu.build-id by
# default; our Mach-O dylib (built with -Dshader-cache=disabled) has none, so Vulkan device init
# aborts with "cannot generate UUID". Mesa's TU_BUILD_ID_OVERRIDE substitutes a fixed hex string.
# Inject the #define directly into the source: passing a quoted string through meson's cross-file
# c_args arrives at clang as \"...\" (meson double-escapes the quote in build.ninja), which is a
# syntax error in strlen(TU_BUILD_ID_OVERRIDE). A source-level define avoids that entirely.
python3 - "$MESA/src/freedreno/vulkan/tu_device.cc" <<'PYEOF'
import sys
p = sys.argv[1]
s = open(p).read()
marker = '#define TU_BUILD_ID_OVERRIDE'
if marker not in s:
    s = '#define TU_BUILD_ID_OVERRIDE "50414e444f52415f4255494c4449445f56315f6269726f6e"\n' + s
    open(p, 'w').write(s)
    print("injected TU_BUILD_ID_OVERRIDE into", p)
else:
    print("TU_BUILD_ID_OVERRIDE already present")
PYEOF
B=$OUT/build
mkdir -p "$B"
cat > "$B/ios.cross" <<EOF
[binaries]
c = '$CC'
cpp = '$CXX'
objc = '$CC'
ar = '$AR'
strip = '$STRIP'
pkg-config = '/usr/bin/false'
[host_machine]
system = 'darwin'
cpu_family = 'aarch64'
cpu = 'arm64'
endian = 'little'
[properties]
needs_exe_wrapper = true
[built-in options]
c_args = $CC_FLAGS
cpp_args = $CC_FLAGS
objc_args = $CC_FLAGS
c_link_args = $BASE_FLAGS
cpp_link_args = $BASE_FLAGS
objc_link_args = $BASE_FLAGS
EOF
OPTIONS=(-Dgallium-drivers= -Dvulkan-drivers=freedreno -Dfreedreno-kmds=darwin "-Dtu-darwin-abi-dir=$ABI"
	-Dplatforms=macos -Dglx=disabled -Degl=disabled -Dgbm=disabled -Dopengl=false -Dgles1=disabled
	-Dgles2=disabled -Dllvm=disabled -Dshared-glapi=disabled -Dxmlconfig=disabled -Dshader-cache=disabled
	-Dtools= -Dbuild-tests=false -Dvideo-codecs= -Dvulkan-layers= -Dlibunwind=disabled -Dlmsensors=disabled
	-Dvalgrind=disabled -Dexpat=disabled -Dzstd=disabled -Dbuildtype=release -Db_ndebug=true
	-Dtu-builtin-source-id=pandora -Dtu-builtin-pack-header=)
env CC="$CC" CXX="$CXX" CFLAGS= CXXFLAGS= CPPFLAGS= LDFLAGS= \
	meson setup "$B/tu" "$MESA" --cross-file "$B/ios.cross" --wrap-mode=nodownload "${OPTIONS[@]}"
ninja -C "$B/tu" src/freedreno/vulkan/libvulkan_freedreno.dylib
LIB=$OUT/libvulkan_freedreno.dylib
cp "$B/tu/src/freedreno/vulkan/libvulkan_freedreno.dylib" "$LIB"
install_name_tool -id /usr/lib/libvulkan_freedreno.dylib "$LIB"
"$STRIP" -x "$LIB"
nm -gU "$LIB" | grep -q ' T _vk_icdGetInstanceProcAddr' || { echo "no vk_icdGetInstanceProcAddr"; exit 1; }
glslangValidator -V --target-env vulkan1.1 --vn fill_spv -o "$B/fill_spv.h" "$ROOT/tools/vktest/fill.comp"
glslangValidator -V --target-env vulkan1.1 --vn tri_vert_spv -o "$B/tri_vert_spv.h" "$ROOT/tools/vktest/tri.vert"
glslangValidator -V --target-env vulkan1.1 --vn tri_frag_spv -o "$B/tri_frag_spv.h" "$ROOT/tools/vktest/tri.frag"
"$CC" -target arm64-apple-ios16.0 -isysroot "$SDK" -O2 -Wall -I "$MESA/include" -I "$B" \
	"$ROOT/tools/vktest/vktest.c" -o "$OUT/vktest"
codesign -s - -f "$LIB" "$OUT/vktest"
otool -L "$LIB" "$OUT/vktest"
(cd "$OUT" && shasum -a 256 libvulkan_freedreno.dylib vktest > SHA256SUMS && cat SHA256SUMS)
ls -l "$LIB" "$OUT/vktest"
