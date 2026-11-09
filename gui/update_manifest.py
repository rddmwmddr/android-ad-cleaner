#!/usr/bin/env python3
"""从已公开的 GitHub Release 元数据生成三端清单；Gitee 回下载校验完成后才能发布。"""
import argparse
import json
import subprocess
from pathlib import Path

try:
    from .updates import SUFFIXES, SOURCES, artifact, version_tuple
except ImportError:
    from updates import SUFFIXES, SOURCES, artifact, version_tuple


def generate(release):
    if release.get('draft') or release.get('prerelease'):
        raise ValueError('只能生成已公开的稳定发行版清单')
    version = release['tag_name'].removeprefix('v')
    version_tuple(version)
    assets = {row['name']: row for row in release['assets']}
    result = dict(schema=1, version=version, artifacts={})
    for target, suffix in SUFFIXES.items():
        name = f'AndroidAdCleaner-{version}-{suffix}'
        asset = assets[name]
        digest = asset.get('digest') or ''
        if not digest.startswith('sha256:'):
            raise ValueError(f'{name} 缺少 GitHub SHA256 摘要')
        result['artifacts'][target] = dict(file=name, size=asset['size'], sha256=digest[7:],
            sources={key: prefix + version + '/' + name for key, prefix in SOURCES.items()})
        artifact(result, target)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    version_tuple(args.version)
    endpoint = 'repos/rddmwmddr/android-ad-cleaner/releases/tags/v' + args.version.removeprefix('v')
    release = json.loads(subprocess.check_output(['gh', 'api', endpoint], text=True, encoding="utf-8", errors="replace"))
    data = generate(release)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
