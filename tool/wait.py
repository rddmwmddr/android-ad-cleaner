#!/usr/bin/env python3
"""「等到页面认得出」与「等机主解锁」的唯一实现。

一次等待只看四件事：采样值认不认得出、最多等多久、多久算稳定、有没有理由提前放弃。
超时与稳定判据都是参数，不再每处各写一份轮询循环（#320）。

判据：
  采样必须为真值才算认出 —— 跳页动画里的空树、空列表都不算页面已经画好；
  给了 changed_from 还要求采样与它不同 —— 「已经换页了」；
  stable / same 给定时，同一个值要同时满足「保持不变满 stable 秒」和「连续读到 same 次」——
  前者管新页面不再重画，后者管「同一开关连续三次读到一样」这类按次数定的判据；
  采样器抛 GiveUp 表示这一页永远认不出来，立刻返回 None。

两种预算，按调用点原来怎么数的选哪种：
  timeout —— 挂钟秒数（页面慢时读屏本身也吃时间，轮数会少一些）；
  tries   —— 采样次数（慢机型上一轮读屏更久，但「最多试 12 次」就是要试满 12 次）。

「等机主解锁」不是 until()：它的循环要先亮屏、再报一句人话、解锁后还要让屏幕站稳，
塞进 until() 就得给它加三个钩子。策略（文案、轮询间隔、站稳时间、默认预算、locked 事件）
留在下面的 wait_unlocked()，调用点只传「现在锁没锁着」和「怎么亮屏」两件机制。

几处等待没有收进来，因为它们的循环里夹着副作用，收进来就得给接口加钩子：
  fast.go、fast.tap(scrolls=0) 的 6 秒（每轮关弹窗）；
  fast._launch() 的三处（等前台包：5 秒只计确知外占、空焦点顺延到 8 秒；等权限弹窗 3 秒；
  等空白页出字 8 秒）；
  chan_fast.ChannelPage._enter_app_page 的翻页循环
  （是翻页不是等待）。

时钟和 sleep 由调用方传：fast / chan_fast 传自己模块里的 time.time / time.sleep，
这样测试里 patch 那个模块的 time 就能换掉等待用的钟，不必改已有测试。
"""
import time

import events

UNSET = object()

# 等解锁的四项策略只在这里定义：默认预算、轮询间隔、解锁后让屏幕站稳的时间、那句人话。
UNLOCK_TIMEOUT = 90
UNLOCK_POLL = 1.0
UNLOCK_SETTLE = 0.8
UNLOCK_TEXT = "  ! 手机锁屏了：请解锁手机并保持亮屏，解锁后自动继续（最多等 {} 秒）"


class GiveUp(Exception):
    """这一页永远认不出来，别再等到超时（vivo 直达的渠道页按规则不能直接用）。"""


def until(sample, timeout=None, poll=0.15, stable=0.0, same=0, tries=None,
          changed_from=UNSET, blocked=None, now=time.monotonic, sleep=time.sleep):
    """等 sample() 认出来：返回认出的那个采样值；超时、到次数、或采样器抛 GiveUp，返回 None。

    每轮先问 blocked（锁屏），只取一次时钟，采样后睡 poll。blocked 返回异常实例就原样抛出，
    返回 GiveUp 则干净地结束。sample 自己抛的其他异常直接冒泡：断线不该被当成「页面没认出来」。

    timeout 与 tries 至少给一个。给了 timeout 时另外按「超时 / 轮询」封顶轮数：
    真机上每轮至少花 poll，挂钟先到；测试把 sleep 换成 no-op 时靠这个上限退出，不会空转。"""
    if timeout is None and tries is None:
        raise ValueError("until() 需要 timeout 或 tries")
    start = now()
    limit = int(timeout / poll) + 1 if timeout is not None and poll > 0 else None
    steady, held = UNSET, None
    rounds = 0
    while True:
        if tries is not None and rounds >= tries:
            return None
        if limit is not None and rounds >= limit:
            return None
        t = now()
        if timeout is not None and t - start >= timeout - 1e-9:
            return None
        if blocked is not None:
            stop = blocked()
            if stop is not None:
                if isinstance(stop, GiveUp):
                    return None
                raise stop
        try:
            value = sample()
        except GiveUp:
            return None
        if value and (changed_from is UNSET or value != changed_from):
            if stable <= 0 and same <= 0:
                return value
            if value != steady:
                steady, held, streak = value, t, 1
            else:
                streak += 1
            if streak >= same and t - held >= stable - 1e-9:
                return value
        else:
            steady, held, streak = UNSET, None, 0
        sleep(poll)
        rounds += 1


# 钟沿用原实现的挂钟（不是 until() 的 monotonic）；两处调用点各传自己模块的 time，测试靠它换假钟。
def wait_unlocked(locked, wake, timeout=UNLOCK_TIMEOUT, now=time.time, sleep=time.sleep):
    """点亮屏幕，等机主解锁（不代替解锁）；等到了返回 True。

    locked() 说自己是否仍锁着，wake() 按一次亮屏。文案、轮询节奏与 locked 事件都在这里发，
    事件每次等待只发一条（真锁着才发，醒来就是解锁状态的发零条）。
    错误日志 10-27：约 15 份报告在开始执行时手机已锁屏，以前直接报失败，后面每一项都重复「锁屏了」。"""
    wake()
    if not locked():
        return True
    print(UNLOCK_TEXT.format(timeout), flush=True)
    events.emit("locked")
    start = now()
    while now() - start < timeout:
        sleep(UNLOCK_POLL)
        if not locked():
            sleep(UNLOCK_SETTLE)
            return True
    return False
