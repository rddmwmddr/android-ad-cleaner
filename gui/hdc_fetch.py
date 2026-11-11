#!/usr/bin/env python3
"""鸿蒙 HDC 的构建期取用：#898。

HDC 与共享库不入库，构建时从 OpenHarmony 官方 SDK 下载、按钉死的 SHA-256 校验、解包，
源码运行时先跑一次本脚本把它取到缓存目录。发行包由 `stage_vendor()` 放进打包资源。

用法：python3 gui/hdc_fetch.py                 取当前平台的工具到缓存
      python3 gui/hdc_fetch.py stage <根目录> [平台]   取到缓存并复制进打包资源
"""
import hashlib
import os
import platform
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

RELEASE = '7.0-Release'
BASE_URL = 'https://repo.huaweicloud.com/openharmony/os/7.0-Release/'
USER_AGENT = 'android-ad-cleaner-build'

# 平台 → 官方 tarball、内层 toolchains zip、以及解出的两个文件。数值来自 #898，
# 与官方 .sha256 和 7.0-Release 包内版本 26.0.0.38-Beta 一致；上游重发包时这里先红。
PLATFORMS = {
    'mac-x64': {
        'tarball': 'ohos-sdk-mac-public.tar.gz',
        'tarball_sha256': '391d76cb90d69b476ae0b65a9f311c572e1a9cdd77da71734af62ed63b108dcc',
        'member': 'sdk/packages/ohos-sdk/darwin/toolchains-darwin-x64-26.0.0.38-Beta.zip',
        'files': {
            'hdc': ('toolchains/hdc',
                    '813eb8d03f88ed211ca51507965e6b269eaa6badc00824de56d8e14e463b3e3a'),
            'libusb_shared.dylib': ('toolchains/libusb_shared.dylib',
                                    'ca969caa3689a318a2e2f06b6cc87371ced640506f8e79abe59a2e98efcdb4dc'),
        },
    },
    'mac-arm64': {
        'tarball': 'L2-SDK-MAC-M1-PUBLIC.tar.gz',
        'tarball_sha256': 'df46e398b391d3406d1eb05e7322c5874f6bf6821e93b1211b36cfcf7a0bbf6f',
        'member': 'sdk/packages/ohos-sdk/darwin/toolchains-darwin-arm64-26.0.0.38-Beta.zip',
        'files': {
            'hdc': ('toolchains/hdc',
                    '0a37c94164e305dd7ea62ffe395dc4f5a336210d00a3e7f9c97d8f1cc92878c3'),
            'libusb_shared.dylib': ('toolchains/libusb_shared.dylib',
                                    '4268da1480ee6950696fd102cedb5627bcdbb6a2928233133460a3dbe6a254c1'),
        },
    },
    'windows': {
        'tarball': 'ohos-sdk-windows_linux-public.tar.gz',
        'tarball_sha256': '130a438cbcddd46a2a5b09ee9925339cddf4cca99223329b860f96a5c72f338f',
        'member': 'ohos-sdk/windows/toolchains-windows-x64-26.0.0.38-Beta.zip',
        'files': {
            'hdc.exe': ('toolchains/hdc.exe',
                        'fa77ab490ab12b10760f01627a894062d12749c4917608fafa96df1860a131c4'),
            'libusb_shared.dll': ('toolchains/libusb_shared.dll',
                                  'e6f475c9e770b02080958e788426aeab8540a6c1fad5c029e83d2f1d72d5e649'),
        },
    },
}


def arch_of(system=None, machine=None):
    """当前（或给定）平台对应的打包目录名，未知平台返回 None。"""
    system = sys.platform if system is None else system
    machine = platform.machine() if machine is None else machine
    if system == 'win32':
        return 'windows'
    if system == 'darwin':
        return 'mac-arm64' if machine == 'arm64' else 'mac-x64'
    return None


def cache_dir(arch, env=None):
    env = os.environ if env is None else env
    base = env.get('AAC_HDC_CACHE')
    base = Path(base) if base else Path.home() / '.cache' / 'android-ad-cleaner' / 'hdc'
    return base / RELEASE / arch


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _download(url, dest):
    dest = Path(dest)
    part = dest.with_name(dest.name + '.part')
    # 华为云镜像对 Python 默认的 User-Agent（Python-urllib/x.y）回 403，换一个就放行（#1050）
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request) as response, open(part, 'wb') as out:
        shutil.copyfileobj(response, out, 1 << 20)
        out.flush()
        os.fsync(out.fileno())
    os.replace(part, dest)


def _exec(path):
    if os.name != 'nt':
        os.chmod(path, 0o755)


def fetch(arch, *, spec=None, downloader=None, cache=None):
    """取两个文件到缓存目录，返回 {文件名: 路径}。已命中缓存时不联网。"""
    spec = PLATFORMS[arch] if spec is None else spec
    root = Path(cache) if cache else cache_dir(arch)
    root.mkdir(parents=True, exist_ok=True)
    targets = {name: root / name for name in spec['files']}
    if all(path.is_file() and _sha256(path) == spec['files'][name][1] for name, path in targets.items()):
        for path in targets.values():
            _exec(path)
        return {name: str(path) for name, path in targets.items()}
    tarball = root / spec['tarball']
    archive = root / (spec['tarball'] + '.toolchains.zip')
    try:
        if not tarball.is_file() or _sha256(tarball) != spec['tarball_sha256']:
            (downloader or _download)(BASE_URL + spec['tarball'], tarball)
            if _sha256(tarball) != spec['tarball_sha256']:
                raise ValueError('鸿蒙工具压缩包校验失败，请检查网络后重试')
        with tarfile.open(tarball, 'r:gz') as tar:
            try:
                member = tar.getmember(spec['member'])
            except KeyError as error:
                raise ValueError(f'压缩包里没有 {spec["member"]}') from error
            with tar.extractfile(member) as source, open(archive, 'wb') as out:
                shutil.copyfileobj(source, out, 1 << 20)
        with zipfile.ZipFile(archive) as bundle:
            for name, (inner, digest) in spec['files'].items():
                try:
                    data = bundle.read(inner)
                except KeyError as error:
                    raise ValueError(f'工具包里没有 {inner}') from error
                if hashlib.sha256(data).hexdigest() != digest:
                    raise ValueError(f'{name} 校验失败，上游可能换了工具')
                part = targets[name].with_name(targets[name].name + '.part')
                part.write_bytes(data)
                _exec(part)
                os.replace(part, targets[name])
        return {name: str(path) for name, path in targets.items()}
    finally:
        for leftover in (tarball, archive):
            leftover.unlink(missing_ok=True)


def stage_vendor(root, arch, *, spec=None, downloader=None, cache=None):
    """把平台工具复制进打包资源 `harmony/desktop/vendor/<平台>/`。"""
    files = fetch(arch, spec=spec, downloader=downloader, cache=cache)
    vendor = Path(root) / 'harmony' / 'desktop' / 'vendor' / arch
    vendor.mkdir(parents=True, exist_ok=True)
    staged = []
    for name, path in files.items():
        target = vendor / name
        shutil.copy2(path, target)
        _exec(target)
        staged.append(str(target))
    return staged


def main(argv):
    args = argv[1:]
    if args[:1] == ['stage']:
        if len(args) < 2:
            print(__doc__, file=sys.stderr)
            return 1
        arch = args[2] if len(args) > 2 else arch_of()
        if arch not in PLATFORMS:
            print('不支持的平台，无法选择鸿蒙工具包', file=sys.stderr)
            return 1
        for path in stage_vendor(args[1], arch):
            print(path)
        return 0
    arch = args[0] if args else arch_of()
    if arch not in PLATFORMS:
        print('不支持的平台，无法选择鸿蒙工具包', file=sys.stderr)
        return 1
    for path in fetch(arch).values():
        print(path)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
