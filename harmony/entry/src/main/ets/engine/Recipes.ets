// 要关的开关清单，也是词库的来源：tools/vocab.py 从这个文件现算 docs/词库.md。
//
// 规矩（从 android-ad-cleaner #681 吸收）：
// - 词条挂 (家族, 分组) 和出处机型。分组名和旧仓库 tool/entries.py 对齐，没有对应的才新起。
// - 只写真机验证过的词。没验证的记进 docs/词条线索.md，实测后才能挪过来。
// - 保留项是页面级的，只约束这一页，不是全局禁词。
// - 词条要写成字面量。新增 Target 写法时同步 tools/vocab.py，否则 tests/test_vocab.py 不过。
//
// 不写进来的：
// - 单个 App 的通知总开关：鸿蒙 7 没有分类开关，关了连订单提醒也没了。
// - 系统更新相关页面：不碰。
// - 还没同意过协议的系统应用：页面看不到，没有依据。

export const FAMILY = '鸿蒙';
const HOP_AL10 = 'HOP-AL10 7.0.0.111';

export type EntryKind = 'uri' | 'home' | 'app';

export class Entry {
  readonly kind: EntryKind;
  // uri：设置页 URI。app：包名。home：空。
  readonly value: string;
  readonly ability: string;
  readonly path: string[];

  constructor(kind: EntryKind, value: string, ability: string, path: string[]) {
    this.kind = kind;
    this.value = value;
    this.ability = ability;
    this.path = path;
  }
}

export class Target {
  readonly title: string;
  // 去广告时拨到的状态。「要求应用请求关联」这类保护开关，打开才算。
  readonly want: boolean;
  // true 表示开关不和文字同行，而在文字下方（华为广告的网页）。
  readonly below: boolean;
  // 页面上有这段文字时不用拨。比如系统通知已关，App 内的推送开关是灰的，也没有推送可关。
  readonly mootWhen: string;
  // 不是开关而是单选项时，从左到右第几个。-1 表示开关。
  readonly radioIndex: number;

  constructor(title: string, want: boolean, below: boolean, mootWhen: string, radioIndex: number) {
    this.title = title;
    this.want = want;
    this.below = below;
    this.mootWhen = mootWhen;
    this.radioIndex = radioIndex;
  }
}

export class Page {
  // 从入口页点进去的路径，处理完按相同次数返回。
  readonly path: string[];
  readonly targets: Target[];
  // 这一页上明确不动的开关。只约束这一页。
  readonly keep: string[];

  constructor(path: string[], targets: Target[], keep: string[]) {
    this.path = path;
    this.targets = targets;
    this.keep = keep;
  }
}

export class Segment {
  readonly id: string;
  readonly name: string;
  readonly group: string;
  // 实测过的机型和系统版本。
  readonly sources: string[];
  readonly entry: Entry;
  readonly pages: Page[];

  constructor(id: string, name: string, group: string, sources: string[], entry: Entry, pages: Page[]) {
    this.id = id;
    this.name = name;
    this.group = group;
    this.sources = sources;
    this.entry = entry;
    this.pages = pages;
  }
}

function off(title: string): Target {
  return new Target(title, false, false, '', -1);
}

function on(title: string): Target {
  return new Target(title, true, false, '', -1);
}

function offBelow(title: string): Target {
  return new Target(title, false, true, '', -1);
}

function offUnlessMuted(title: string): Target {
  return new Target(title, false, false, '通知已关闭', -1);
}

// 单选项的文字读屏读不到，按位置认。还原时点同一组里的另一个。
function choose(title: string, radioIndex: number): Target {
  return new Target(title, true, false, '', radioIndex);
}

function uri(value: string, path: string[]): Entry {
  return new Entry('uri', value, '', path);
}

function home(path: string[]): Entry {
  return new Entry('home', '', '', path);
}

function app(bundle: string, ability: string, path: string[]): Entry {
  return new Entry('app', bundle, ability, path);
}

export const SEGMENTS: Segment[] = [
  new Segment('ads', '华为广告', '系统广告', [HOP_AL10],
    uri('privacy_settings', ['数据和隐私', '华为广告', '广告偏好设置']),
    [new Page([], [offBelow('个性化广告')], [])]),
  new Segment('tracking', '跨应用关联', '跟踪管理', [HOP_AL10],
    uri('privacy_settings', ['跨应用关联']),
    [new Page([], [on('要求应用请求关联')], [])]),
  new Segment('search', '小艺搜索', '下拉搜索', [HOP_AL10],
    home(['小艺', '小艺搜索']),
    [new Page([], [off('热搜榜'), off('小艺建议')], ['搜索历史', '智能体'])]),
  new Segment('feed', '负一屏', '负一屏', [HOP_AL10],
    home(['桌面和个性化', '桌面设置', '负一屏']),
    [
      // 卡片里有快递和天气，属于正常功能。
      new Page([], [off('资讯')], ['卡片']),
      new Page(['个性化推荐'], [off('个性化推荐')], []),
    ]),
  new Segment('browser', '浏览器', '浏览器', [HOP_AL10],
    app('com.huawei.hmos.browser', 'MainAbility', ['我的', '设置']),
    [
      new Page(['消息通知'], [off('应用内资讯推送')], ['互动消息', '订阅通知']),
      // 主页设置是二选一：默认主页带资讯流，简洁主页只有搜索框和快捷入口。
      new Page(['主页设置'], [choose('简洁主页', 1)], []),
      new Page(['个性化推荐'], [off('个性化推荐')], []),
      new Page(['个性化搜索建议'], [off('个性化搜索建议')], []),
    ]),
  new Segment('market', '应用市场', '应用市场', [HOP_AL10],
    app('com.huawei.hmsapp.appgallery', 'MainAbility', ['我的', '设置']),
    [
      new Page(['个性化推荐'], [off('个性化推荐')], []),
      new Page(['消息通知'], [offUnlessMuted('应用活动与资讯')], []),
    ]),
  new Segment('telemetry', '用户体验改进计划', '用户体验计划', [HOP_AL10],
    uri('system_and_updates', ['用户体验改进计划']),
    [new Page([], [off('加入用户体验改进计划')], [])]),
];
