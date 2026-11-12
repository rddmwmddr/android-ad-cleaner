"""工具层共用的 `gh` 会话：起进程、判 JSON、报错各只有一处实现（#1217）。

`runner` 是注入点，签名 `(script, *args) -> (标准输出, 错误输出, 返回码)`，与用例里的 FakeRunner
同形；不想注入的调用方用 `runner_for()` 取默认执行器。

失败只有 `GhError` 一种类型，措辞三档：跑不了 gh、退出码非零、输出不是 JSON。改报错方式时只改这里。
"""
import json
import subprocess


class GhError(RuntimeError):
    """取不到数据：跑不了 `gh`、退出码非零、输出不是 JSON——三种都给不出结局。

    喂进来的输入（如标签审计的 `--input` 落盘）读不了也算这一族：调用方只看「取到没取到」，
    不分辨数据是从网线来的还是从磁盘来的。
    """


def runner_for(cwd=None, timeout=None):
    """默认的 `gh` 执行器。

    `timeout` 默认不设：慢网络不该被判成失败，只有本身有时限的那一步才传秒数。
    """
    def run(script, *args):
        done = subprocess.run([script, *args], cwd=cwd, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return done.stdout, done.stderr, done.returncode
    return run


def call(runner, *args):
    """一次 `gh` 调用 -> (标准输出或错误文本, 返回码)。

    失败时取错误输出，为空时退回标准输出；两端都 strip。跑不了 `gh`（没装、不在 PATH 上）
    也归进 `GhError`，调用方只处理一种失败。
    """
    try:
        out, err, rc = runner("gh", *args)
    except OSError as error:
        raise GhError(f"跑不了 gh：{error}") from error
    return (out if rc == 0 else (err or out)).strip(), rc


def json_of(runner, *args, source):
    """跑一次 `gh` 并判读 JSON；`source` 是这条命令的来源说明，写进报错里。"""
    text, rc = call(runner, *args)
    if rc != 0:
        raise GhError(f"{source} 退出码非零：{text or 'gh 返回非零'}")
    try:
        return json.loads(text)
    except ValueError as error:
        raise GhError(f"{source} 的输出不是 JSON：{error}") from error
