"""拨动会话：整页开关的关与开、确认框、回读、补点、结局（ADR-0033、#1040）。

`off()` 只做点击 → 回读 → 重试 → 报告；拨动计划、回读、补点落点是同名的纯函数，与编排一起留在
这里。动作与观测只经 `Screen`——确认框的认法也在基座（`Screen.confirm_target`），所以导航侧
失败时那句残留提示直接问基座，不再回指拨动。
"""
import re
import time
import unicodedata
from dataclasses import dataclass

import wait
from polarity import TRACK_WORDS, want_state
from row import disabled_at

# 点击后认确认框总共等多久：vivo 商店「个性化推荐」页的弹窗要 0.6 秒才进树，而一次读屏
# 也要上百毫秒，1 秒是「能等到慢弹窗」与「没弹窗的页面不多付太多」之间的取值（#555）。
# 前 0.2 秒先不给读屏：弹窗刚弹出时按钮还在动，点在半路上不生效。
# 预算按挂钟算、读屏本身也吃时间：dump 慢到 0.5 秒的机型只采得到两次样，晚于 1 秒才进树的
# 弹窗仍会漏，那时靠 `off()` 连点前的遮罩检查兜一次。
CONFIRM_WAIT = 1.0
CONFIRM_SETTLE = 0.2


@dataclass(frozen=True)
class SwitchPlan:
    """一页的拨动计划：要拨的目标、核对过的开关、安全模式放过的开关、被上级开关禁用的开关。"""
    targets: tuple
    checked: frozenset
    kept: frozenset
    disabled: frozenset = frozenset()


def in_band(xy, screen_h):
    """行的落点在可点带内：避开顶部标题栏与底部栏。"""
    return screen_h * 0.08 <= xy[1] <= screen_h * 0.985


def match_key(text):
    """keep/only 的归一化匹配键（#559）：NFKC 统一全角半角（「：」→「:」、「Ａ」→「A」、
    全角空格→空格），去掉全部空白与常见中英标点，再小写。标题与保留词 / 名单词两侧
    用同一套——只归一化一边等于没修。「应用安全」与「安全内容推荐」归一化后仍是两个键。
    want_state() 的语义不动：它判「该开还是该关」，归一化只管「要不要碰」。"""
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"[\s\u3000]+", "", text)
    text = re.sub(r"[，。：；、！？·「」『』（）【】—－–,.:;!?()(\[\]){}\"'~*#@&%$+=|<>]", "", text)
    return text.lower()


MATCH_EXACT = 2      # 归一化后与名单词完全相等
MATCH_FRAGMENT = 1   # 只是包含了名单词


def match_rank(key, keys):
    """一行标题对名单的命中精度：精确（归一化后相等）高于子串，没命中是 0。
    keys 为 None 表示调用方没给名单。"""
    if not keys:
        return 0
    if key in keys:
        return MATCH_EXACT
    return MATCH_FRAGMENT if any(k in key for k in keys) else 0


def plan_switches(rows, keep=(), only=None, safe_mode=False, *, screen_h, disabled=None):
    """这一页该拨哪些开关。rows 是 `Screen.switches()` 的输出；函数不读屏、不点击。

    targets 只含需要点击的行；checked 是过了筛选的标题，含已在目标态、落在屏带外与被禁用的；
    kept 是安全模式放过的普通开关。disabled 是按坐标判「这一行的开关是灰的」的谓词：
    命中的行不进 targets，也不报成拨不动。screen_h 无默认值：带过滤是这一页几何的一部分。
    keep/only 的匹配走 match_key 归一化（#559）：页面标题的字间空格、全角标点与脚本里
    写的保留词不一致时（「首页 AI 搜索」vs「首页：AI搜索」），保留词照样命中。

    命中的精度决定谁先：keep 仍然压过 only，唯一例外是 only 精确点名了这一行、keep 只是
    子串命中它的标题（#861）。close_named() 把整页未点名的行都塞进 keep，短保留词会连带
    吞掉以它为前缀的目标行（「应用安全」吞掉「应用安全安全内容推荐」）。判据只看这一行
    自己的两次命中，不依赖同名行是否也在本屏——plan_switches() 每屏调用一次，多屏页面上
    保留词的同名行可能在别的屏。"""
    keep_keys = {match_key(k) for k in keep if match_key(k)}
    only_keys = {match_key(k) for k in only if match_key(k)} if only is not None else None
    checked, kept, candidates = set(), set(), []
    for title, state, xy, *_ in rows:
        if not title:
            continue
        key = match_key(title)
        want = want_state(title)
        if want is None:
            continue
        keep_rank = match_rank(key, keep_keys)
        only_rank = match_rank(key, only_keys)
        if keep_rank and not (only_rank == MATCH_EXACT and keep_rank == MATCH_FRAGMENT):
            continue
        if only_keys is not None and not only_rank and not (want and TRACK_WORDS.search(title)):
            continue                              # 「限制广告跟踪」这类保护开关：不在名单里也要打开
        if safe_mode and only is None and not want:
            kept.add(title)
            continue                              # 参考脚本（同品牌别的机型录的）：不做整页全关
        checked.add(title)
        if state == want:
            continue
        if not in_band(xy, screen_h):
            continue
        candidates.append((title, xy, want))
    greyed = greyed_titles(((t, xy) for t, xy, _ in candidates), disabled) if disabled else set()
    targets = tuple(c for c in candidates if c[0] not in greyed)
    return SwitchPlan(targets, frozenset(checked), frozenset(kept), frozenset(greyed))


def greyed_titles(pairs, disabled):
    """这些 (标题, 落点) 里同名行全部被判灰的标题。同一屏可能有两个同名开关（双列卡片），
    一个灰一个正常时，不能因为一个灰就把另一个的失败也当成灰态吞掉（#333）。"""
    flags = {}
    for title, xy in pairs:
        flags.setdefault(title, []).append(disabled(xy))
    return {title for title, found in flags.items() if all(found)}


# 一屏回读后每条目标的结局。只有前两个算拨到了：VANISHED 是点过之后整行从列表消失（#486），
# 灰态单列一档，因为它的说法与失败不同（「被上级开关禁用」而不是「关不掉」，#333）。
REACHED = "reached"      # 到了目标态（关掉；保护类开关则是打开）
VANISHED = "vanished"    # 点过之后整行从列表消失，按已关记账
MISSED = "missed"        # 没到目标态
GREYED = "greyed"        # 没到目标态，且开关是灰的


def readback(targets, rows, *, clicked, others, page_same, disabled):
    """一屏回读：{标题: 结局}。不读屏、不点击。

    targets 是 `plan_switches()` 的输出；rows 是这一次读到的 (`Screen.switches()` 格式)；
    clicked 是本屏真的点过的标题；others 是本屏计划时见过的非目标标题；disabled 是按落点判灰的谓词。
    page_same 是零参数可调用对象，只在「点过、且行已从列表消失」时才被问，答这一页还是原来那页。
    结局按标题合并：同名行的任意一行没到目标态就算没到（#403）。
    """
    states = {}
    for title, on, *_ in rows:
        states.setdefault(title, []).append(on)
    out = {}
    for t, _, w in targets:
        seen = states.get(t)
        if seen is not None:
            out[t] = REACHED if all(on == w for on in seen) else MISSED
        elif t in clicked and rows and not w:
            # 点过的普通开关行从列表里消失了：回读里还有本屏计划时见过的非目标行，
            # 且没跳走，才算随行消失。整页读空、换成标题全新的页（同 Activity 的子页）
            # 时这一页已无法核对，不能把读屏失败当成关闭成功（#486）。
            # 保护类开关是「主动打开」，行消失证明不了它开了，仍报打不开。
            out[t] = VANISHED if page_same() and others & states.keys() else MISSED
        else:
            out[t] = MISSED
    for t in still_greyed(targets, rows, {t for t, v in out.items() if v == MISSED}, disabled):
        out[t] = GREYED
    return out


def still_greyed(targets, rows, titles, disabled):
    """rows 里这些标题中、还没到目标态、且同名行全被判灰的那几个（#333）。
    回读与补点共用这一份判据：每次都要按当次读到的落点重新算，不能沿用上一次的。"""
    want = {t: w for t, _, w in targets}
    return titles & greyed_titles(
        ((title, xy) for title, on, xy, *_ in rows
         if title in titles and on != want[title]), disabled)


def still_open(verdicts):
    """回读里还没到目标态的标题（灰的也算在里面）：补点只看这一批。"""
    return {t for t, v in verdicts.items() if v in (MISSED, GREYED)}


def pick_retry_rows(targets, rows, still, disabled):
    """该补点的那一行：一标题一行、跳过灰的、按状态而不是按标题挑（#403）。
    rows 是新读的一屏，不能沿用消失节点的旧坐标；顺序跟着拨动计划。"""
    want = {t: w for t, _, w in targets}
    grey = still_greyed(targets, rows, still, disabled)
    picked = []
    for t, w in want.items():
        if t not in still or t in grey:
            continue
        row = next(((on, at) for title, on, at, *_ in rows
                    if title == t and on != w and not disabled(at)), None)
        if row is not None:
            picked.append((t, row[1]))
    return picked


def pick_title_rows(targets, rows, still, disabled):
    """回退到行标题时该点哪些行：挑哪几行交给 `pick_retry_rows`，落点换成同一行的标题（#608）。
    rows 是 `Screen.switch_rows()` 的四元组；没有独立标题的行不点——点它的标题等于再点一次本体。"""
    hits = {(title, xy): hit for title, _, xy, hit in rows if hit is not None}
    return [(t, hits[(t, xy)])
            for t, xy in pick_retry_rows(targets, rows, still, disabled) if (t, xy) in hits]


class Toggler:
    """拨动会话：一页一页地把开关拨到目标态，并把结局记下来。

    `safe_mode` 与 `changed` 归它：前者只在这里读，后者只在这里写。门面用显式属性转发，
    脚本的 `p.safe_mode = …` 与 `p.changed.append(...)` 照旧可用。
    """

    def __init__(self, screen, lost_note):
        self.screen = screen
        self.lost_note = lost_note                 # 丢失记录：off() 读 `miss`、读写 `missed`（ADR-0033）
        self.safe_mode = False           # 安全模式（参考脚本 / 录制版本不符）：只关点名的开关，不做整页全关
        self.changed = []                # (页面, 标题) 记录本次关掉的

    def confirm(self):
        """开关后弹确认框就点确认类按钮，认出即返回按钮文字；没有弹窗返回 None。

        弹窗进树可能远慢于一次读屏（vivo 商店这一页要 0.6 秒），单次快照从点击那一刻起就
        必然错过，剩下的点击会落在遮罩上被吞（#555）。所以在 CONFIRM_WAIT 预算内轮询。"""
        time.sleep(CONFIRM_SETTLE)
        found = wait.until(self.screen.confirm_target, timeout=CONFIRM_WAIT - CONFIRM_SETTLE,
                           poll=0.1, now=time.time, sleep=time.sleep)
        if found is None:
            return None
        label, xy = found
        self.screen.click(*xy)
        time.sleep(0.3)
        return label

    def off(self, keep=(), only=None, page="", max_screens=40):
        """当前列表：关掉开着的开关。keep=标题含这些词的不动；only=只关含这些词的。
        only 精确点名、keep 只是子串命中同一行时按 only（#861）。
        每屏第一下单独点、看有没有弹窗/跳页；没有就把这一屏剩下的连着点完，最后统一核对。
        关掉一项这一行就消失的页面（下面的行整体上移）：从下往上点，上移的只可能是已经点过的行；
        首击后剩下的目标若已不在原坐标，这一屏剩下的改成每点一项前重读坐标（#480）。
        点过的普通开关行在回读里消失、回读仍见到本屏计划时的非目标行且没跳走，按已关记账；
        整页读空、换到别的页（含同 Activity 的子页）或保护类开关消失，仍报失败（#486）。
        开关是灰的（被上级开关禁用）的行不点、也不算失败：点了也不会变，以前报成「关不掉」（#333）。
        补点两轮仍没到位的，回退到点整行标题（只认行标题的页面，ADR-0024）：照样由回读确认。
        仍没拨到目标态的记进丢失记录：光打一行 ✗ 的话退出码还是 0、结果页标「成功」（#788）。"""
        screen = self.screen
        # 页面刚打开还没画完：等开关出现，最多试 10 次（本段已走丢就不等）
        wait.until(screen.switches, tries=2 if self.lost_note.miss else 10, poll=0.2,
                   now=time.time, sleep=time.sleep)
        start = screen.focus()
        done, slow, checked, kept, greyed = 0, False, set(), set(), set()

        def plan_page(root):
            rows = screen.switches(root)
            return (plan_switches(rows, keep, only, self.safe_mode, screen_h=screen.H,
                                  disabled=lambda xy: disabled_at(root, xy)), rows)

        for _ in range(max_screens):
            root = screen.tree()
            plan, planned = plan_page(root)
            if plan.disabled:
                # 开关可能在页面加载中短暂不可用：复读一次再定，别把恢复可用的开关整屏跳过（#333）
                root = screen.tree()
                plan, planned = plan_page(root)
            checked |= plan.checked
            for t in plan.checked:                      # 已经到位的：上一屏或上一次 off() 记的那条不再算没拨动
                if (page, t) in self.lost_note.missed:
                    self.lost_note.missed.remove((page, t))
            kept |= plan.kept
            page_greyed = set(plan.disabled)
            targets = plan.targets
            others = {title for title, _, _ in planned if title} - {t for t, _, _ in targets}
            order = list(reversed(targets))             # 先点下面的：它消失时上移的只可能是已点过的行
            shift = False                               # 剩下的目标是不是还准在计划坐标上
            clicked = set()                             # 本屏真的点过的标题：点完从列表消失的靠它认
            for i, (t, xy, w) in enumerate(order):
                if i and not slow and screen.confirm_target() is not None:
                    # 首击的确认框比 confirm() 的等待还慢时，页面还盖着遮罩：连点下去全被吞（#555）
                    self.confirm()
                if i and shift:
                    # 页面重排过：每点一项前重读，旧坐标可能已经指向邻行
                    time.sleep(0.3)                     # 等行消失、列表上移的动画走完
                    root = screen.tree()
                    rows = screen.switches(root)
                    row = next(((on, at) for title, on, at, *_ in rows
                                if title == t and on != w), None)
                    if row is None or not in_band(row[1], screen.H) or disabled_at(root, row[1]):
                        continue                        # 已不在、已到位、已在带外或已变灰：交给收尾回读
                    xy = row[1]
                screen.click(*xy)
                clicked.add(t)
                if i == 0 or slow:
                    if self.confirm():
                        slow = True                     # 这页会弹确认框，逐个点
                    elif screen.focus() != start:
                        screen.say(f"  ! 页面变了（{screen.focus()}），停")
                        screen.back()
                        return done
                if i == 0 and len(order) > 1:
                    time.sleep(0.3)                     # 等动画走完，再看剩下的是不是还在原处
                    now = {(title, on, at) for title, on, at in screen.switches()}
                    shift = any((t2, not w2, xy2) not in now for t2, xy2, w2 in order[1:])
                elif i and not slow:
                    time.sleep(0.06)
            if targets:
                time.sleep(0.25)
                self.confirm()

                def read_page():                        # 这一屏的回读：({标题: 结局}, 这次读到的树)
                    root = screen.tree()
                    rows = screen.switches(root)
                    stayed = []                         # 惰性查：没有消失行时不额外读一次前台

                    def page_same():
                        if not stayed:
                            stayed.append(screen.focus() == start)
                        return stayed[0]
                    return readback(targets, rows, clicked=clicked, others=others,  # noqa: B023 - 本屏的 targets / clicked / others 当轮创建，read_page 同步调用
                                    page_same=page_same,
                                    disabled=lambda xy: disabled_at(root, xy)), root  # noqa: B023 - lambda 的 xy 是形参，root 是本屏读到的树

                def retry(still):
                    # 只重试当前仍能识别的开关，不能在节点消失后沿用旧坐标；灰掉的点了也不会变。
                    if not still:
                        return
                    here = screen.focus()
                    if here and here != start:
                        return                          # 页面已经换了：新页上的同名行不是这一屏的开关
                                                        # here 为空只是这一次没读到前台，不拦补点
                    root = screen.tree()
                    rows = screen.switches(root)
                    for t, xy in pick_retry_rows(targets, rows, still,  # noqa: B023 - targets 当轮创建，pick_retry_rows 同步调用
                                                 lambda xy: disabled_at(root, xy)):
                        screen.click(*xy); self.confirm()
                        clicked.add(t)                  # 补点也算点过：行随后消失同样是随行消失（沿用 #486）  # noqa: B023 - clicked 当轮创建

                def retry_titles(still, root):
                    # 开关本体点了不动、只认行标题的页面（Google 广告设置页，#608）：改点这一行的标题。
                    # 每点一次都按新树重取坐标：点掉一行会让下面的行整体上移，旧坐标会落到邻行（#480 同一口子）。
                    done_here, pending = False, set(still)
                    while pending:
                        picked = pick_title_rows(targets, screen.switch_rows(root), pending,  # noqa: B023 - targets 当轮创建，pick_title_rows 同步调用
                                                 lambda xy: disabled_at(root, xy))  # noqa: B023 - lambda 的 xy 是形参，root 是 retry_titles 的入参
                        if not picked:
                            break                       # 没有独立标题可点：不多读前台、也不多回读
                        here = screen.focus()
                        if here and here != start:
                            break                       # 页面已经换了：新页上的同名行不是这一屏的开关
                        t, xy = picked[0]
                        screen.click(*xy); self.confirm()
                        clicked.add(t)  # noqa: B023 - clicked 当轮创建
                        done_here, pending = True, pending - {t}
                        here = screen.focus()
                        if here and here != start:      # 标题不是开关：有的页面点它进的是详情页
                            screen.back()
                            break
                        if pending:
                            time.sleep(0.3)             # 等行消失 / 列表上移的动画走完
                            root = screen.tree()
                    return done_here
                verdicts, root = read_page()
                still = still_open(verdicts)
                retry(still)
                verdicts, root = read_page()
                still = still_open(verdicts)
                if still:                               # 还有没拨过去的：等动画结束再点一次
                    time.sleep(0.8)
                    retry(still)
                    time.sleep(0.4)
                    verdicts, root = read_page()
                    still = still_open(verdicts)
                if still and retry_titles(still, root):
                    time.sleep(0.4)                     # 点标题后可能弹确认框 / 改状态：复读确认
                    verdicts, _ = read_page()
                # 这一屏关到一半才变灰的，同样不报成拨不动
                page_greyed |= {t for t, v in verdicts.items() if v == GREYED}
                for t, _, w in targets:
                    v = verdicts[t]
                    if v == GREYED:
                        continue                        # 下面单独说明
                    if v == MISSED:
                        screen.say(f"  ✗ {'打不开' if w else '关不掉'} {t}")
                        if (page, t) not in self.lost_note.missed:      # 滚动后同一行会再成为目标
                            self.lost_note.missed.append((page, t))
                    else:
                        screen.say(f"  {'开（保护类开关）' if w else '关'} {t}"
                                   + ("（点后从列表消失）" if v == VANISHED else ""))
                        self.changed.append((page, t))
                        if (page, t) in self.lost_note.missed:          # 下一屏补点拨到了
                            self.lost_note.missed.remove((page, t))
                        done += 1
            for t in page_greyed - greyed:
                screen.say(f"  · 被上级开关禁用（开关是灰的），未改动 {t}")
            greyed |= page_greyed
            if not screen.scroll_more():
                break
        if page:
            if kept and not checked:
                # 页面找到了，只是安全模式不整页全关；不能写成「未找到」
                screen.say(f"  · {page}：安全模式不做整页全关，本页 {len(kept)} 个开关未改动，需要时请按清单手动关")
            else:
                screen.say(f"  · {page}：核对 {len(checked)} 项，调整 {done} 项" + ("（本页未找到目标开关）" if not checked else ""))
        return done
