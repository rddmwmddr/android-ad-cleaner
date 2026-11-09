// 通过 hdc shell 读屏和点击。不用 uitest 的文字输入，它会经过剪贴板。
import { hilog } from '@kit.PerformanceAnalysisKit';
import { HdcClient } from '../hdc/HdcClient';
import { Item, LayoutNode, Rect, Screen } from './Screen';
import { Target } from './Recipes';

const DUMP_PATH = '/data/local/tmp/roudai_layout.json';
const SETTINGS_BUNDLE = 'com.huawei.hmos.settings';
const SETTINGS_ABILITY = 'com.huawei.hmos.settings.MainAbility';
const SHELL_TIMEOUT_MS = 20000;
const SETTLE_MS = 500;
const OPEN_SETTLE_MS = 1200;
const FIND_PAGES = 6;
const VERIFY_TRIES = 5;
const WAIT_MS = 9000;
// 网页开关加载慢，看到开关才继续，最多等这么久。
const WEB_WAIT_MS = 60000;
const WEB_STEPS = 14;
const SMALL_STEP = 0.35;
const MIN_WEB_AREA = 200000;
const BOTTOM_MARGIN = 40;
// 只认拨开关引出的确认。不含「同意」「允许」这类授权的词。
const CONFIRM_WORDS: string[] = ['确认停用', '仍要关闭', '确认关闭', '关闭', '确定', '确认', '继续', '知道了'];

export type SwitchOutcome = 'changed' | 'already' | 'moot' | 'missing' | 'locked' | 'failed';

export class SwitchResult {
  readonly outcome: SwitchOutcome;
  // 拨动前的状态。找不到开关时没有意义。
  readonly before: boolean;

  constructor(outcome: SwitchOutcome, before: boolean) {
    this.outcome = outcome;
    this.before = before;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });
}

export class Phone {
  private readonly client: HdcClient;

  constructor(client: HdcClient) {
    this.client = client;
  }

  shell(command: string): Promise<string> {
    return this.client.shell(command, SHELL_TIMEOUT_MS);
  }

  async read(): Promise<Screen> {
    let lastError: Error = new Error('读屏失败');
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const raw = await this.shell(
          `rm -f ${DUMP_PATH}; uitest dumpLayout -p ${DUMP_PATH} >/dev/null 2>&1; cat ${DUMP_PATH}; rm -f ${DUMP_PATH}`);
        return new Screen(JSON.parse(raw) as LayoutNode);
      } catch (error) {
        lastError = error as Error;
      }
    }
    throw lastError;
  }

  async tapAt(x: number, y: number): Promise<void> {
    await this.shell(`uitest uiInput click ${x} ${y}`);
    await sleep(SETTLE_MS);
  }

  async back(): Promise<void> {
    await this.shell('uitest uiInput keyEvent Back');
    await sleep(SETTLE_MS);
  }

  async openSettingsUri(uri: string): Promise<void> {
    await this.shell(`aa force-stop ${SETTINGS_BUNDLE}`);
    await this.shell(`aa start -b ${SETTINGS_BUNDLE} -a ${SETTINGS_ABILITY} -U '${uri}'`);
    await sleep(OPEN_SETTLE_MS);
  }

  // 不带页面打开设置。展开时右栏默认是系统更新页，只点左栏，那一页不碰。
  async openSettingsHome(): Promise<void> {
    await this.shell(`aa force-stop ${SETTINGS_BUNDLE}`);
    await this.shell(`aa start -b ${SETTINGS_BUNDLE} -a ${SETTINGS_ABILITY}`);
    await sleep(OPEN_SETTLE_MS);
  }

  async openApp(bundle: string, ability: string): Promise<void> {
    await this.shell(`aa force-stop ${bundle}`);
    await this.shell(`aa start -b ${bundle} -a ${ability}`);
    await sleep(OPEN_SETTLE_MS);
  }

  async bringToFront(bundle: string, ability: string): Promise<void> {
    await this.shell(`aa start -b ${bundle} -a ${ability}`);
  }

  // 手指向上划，内容往下走。up 为 true 时反过来，回到页面上方。
  private async swipe(screen: Screen, area: Rect, up: boolean, fraction: number = 0.6): Promise<void> {
    const x = screen.swipeColumn(area);
    const half = Math.floor(area.height * fraction / 2);
    const low = area.centerY + half;
    const high = area.centerY - half;
    const from = up ? high : low;
    const to = up ? low : high;
    await this.shell(`uitest uiInput swipe ${x} ${from} ${x} ${to} 300`);
    await sleep(SETTLE_MS);
  }

  private findIn(screen: Screen, title: string): Item | undefined {
    const item = screen.findText(title);
    if (item !== undefined && item.rect.bottom < screen.windowRect.bottom - BOTTOM_MARGIN) {
      return item;
    }
    return undefined;
  }

  // 把每个滚动区先往下再往上翻一遍找文字，返回文字所在的那一屏。
  // 从子页返回时列表停在原来的位置，要找的行可能在上方。
  async findByScrolling(title: string): Promise<Screen | undefined> {
    let screen = await this.read();
    if (this.findIn(screen, title) !== undefined) {
      return screen;
    }
    for (const area of screen.scrollAreas()) {
      for (const up of [false, true]) {
        let last = screen.signature();
        for (let page = 0; page < FIND_PAGES * (up ? 2 : 1); page++) {
          await this.swipe(screen, area, up);
          screen = await this.read();
          if (this.findIn(screen, title) !== undefined) {
            return screen;
          }
          const signature = screen.signature();
          if (signature === last) {
            break;
          }
          last = signature;
        }
      }
    }
    return undefined;
  }

  // App 冷启动后等页面出来：看到入口文字或协议页就算好了。超时也继续，由后面的查找报没找到。
  async waitForReady(title: string): Promise<void> {
    const deadline = Date.now() + WAIT_MS;
    while (Date.now() < deadline) {
      const screen = await this.read();
      if (screen.hasText(title) || screen.hasConsent()) {
        return;
      }
      await sleep(SETTLE_MS);
    }
  }

  async tapText(title: string): Promise<boolean> {
    const screen = await this.findByScrolling(title);
    if (screen === undefined) {
      return false;
    }
    const item = this.findIn(screen, title) as Item;
    await this.tapAt(item.rect.centerX, item.rect.centerY);
    return true;
  }

  private radiosOf(screen: Screen): Item[] {
    return screen.items.filter((item: Item) => item.type === 'Radio' && item.rect.area > 0)
      .sort((a: Item, b: Item) => a.rect.left - b.rect.left);
  }

  private controlOf(screen: Screen, target: Target): Item | undefined {
    if (target.radioIndex >= 0) {
      const radios = this.radiosOf(screen);
      return target.radioIndex < radios.length ? radios[target.radioIndex] : undefined;
    }
    for (const label of screen.findAllText(target.title)) {
      const control = target.below ? screen.switchBelow(label) : screen.switchFor(label);
      if (control !== undefined) {
        return control;
      }
    }
    return undefined;
  }

  // 开关在网页里：先等网页出来，再只在网页里往下翻，直到开关出现。
  // 这类网页读一次屏要好几秒，内容也要滚到附近才读得到，不能用通用的翻页找法。
  private async findInWeb(target: Target): Promise<Screen | undefined> {
    const deadline = Date.now() + WEB_WAIT_MS;
    let screen: Screen | undefined = undefined;
    let web: Rect | undefined = undefined;
    while (Date.now() < deadline) {
      screen = await this.read();
      const found = screen.items.find((item: Item) => item.type === 'Web' && item.rect.area >= MIN_WEB_AREA);
      if (found !== undefined) {
        web = found.rect;
        break;
      }
      await sleep(SETTLE_MS * 2);
    }
    if (screen === undefined || web === undefined) {
      return screen;
    }
    for (let step = 0; step < WEB_STEPS && Date.now() < deadline; step++) {
      if (this.controlOf(screen, target) !== undefined) {
        return screen;
      }
      const fraction = screen.findAllText(target.title).length > 0 ? SMALL_STEP : 0.5;
      await this.swipe(screen, web, false, fraction);
      screen = await this.read();
    }
    return screen;
  }

  private async findControl(target: Target): Promise<Screen | undefined> {
    if (target.radioIndex >= 0) {
      return this.read();
    }
    if (target.below) {
      return this.findInWeb(target);
    }
    return this.findByScrolling(target.title);
  }

  // 找到文字却认不出开关时，把现场写进日志。只写开关和这段文字，不写屏幕上的其他内容。
  private logMissing(screen: Screen, target: Target): void {
    const labels = screen.findAllText(target.title).map((item: Item) => `${item.type}@${item.rect.left},${item.rect.top}`);
    const controls = screen.items.filter((item: Item) => item.checkable)
      .map((item: Item) => `${item.type}@${item.rect.left},${item.rect.top},${item.rect.right},${item.rect.bottom}`);
    hilog.warn(0x0001, 'RoudaiRun', '认不出开关 %{public}s 文字 %{public}s 开关 %{public}s',
      target.title, labels.join(' '), controls.join(' '));
  }

  // 把开关拨到 want，拨完回读确认。
  async setSwitch(target: Target, want: boolean): Promise<SwitchResult> {
    const screen = await this.findControl(target);
    if (screen === undefined) {
      return new SwitchResult('missing', false);
    }
    const control = this.controlOf(screen, target);
    if (control === undefined) {
      this.logMissing(screen, target);
      return new SwitchResult('missing', false);
    }
    const before = control.checked;
    if (before === want) {
      return new SwitchResult('already', before);
    }
    if (target.mootWhen !== '' && screen.hasText(target.mootWhen)) {
      return new SwitchResult('moot', before);
    }
    if (!control.enabled) {
      return new SwitchResult('locked', before);
    }
    let point: Rect = screen.tapTarget(control);
    if (target.radioIndex >= 0 && !want) {
      // 单选项不能直接取消，点同一组里的另一个。
      const other = this.radiosOf(screen).find((item: Item) => item !== control);
      if (other === undefined) {
        return new SwitchResult('missing', before);
      }
      point = other.rect;
    }
    await this.tapAt(point.centerX, point.centerY);
    for (let attempt = 0; attempt < VERIFY_TRIES; attempt++) {
      const after = await this.read();
      const current = this.controlOf(after, target);
      if (current !== undefined && current.checked === want) {
        return new SwitchResult('changed', before);
      }
      const button = after.findConfirm(CONFIRM_WORDS);
      if (button !== undefined) {
        await this.tapAt(button.rect.centerX, button.rect.centerY);
      } else {
        await sleep(SETTLE_MS);
      }
    }
    return new SwitchResult('failed', before);
  }
}
