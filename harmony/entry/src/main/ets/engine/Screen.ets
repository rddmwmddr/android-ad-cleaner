// 一屏的读屏结果。uitest dumpLayout 把所有窗口、所有层的节点都列出来，
// 被盖住的页面也报 visible=true，要靠层叠顺序和位置判断哪些真的看得见。
//
// 折叠时一屏一页；展开时左栏是列表、右栏是详情，两边都看得见。
// 规则：树里靠后的 NavDestination / Dialog 盖在靠前的上面，被盖住一半以上的整页不算；
// 不属于任何页的节点，排在最上层页后面的算（比如浮动底栏），排在前面的只有落在可见页范围外才算（左栏）。

const SYSTEM_UI = 'com.ohos.sceneboard';
const INVISIBLE_CHARS = /[​-‏‪-‮⁠﻿]/g;
// 开关和标题的中心相差多远以内算同一行。行高一般在 130 到 180 之间。
const SAME_ROW_DISTANCE = 110;
// 小于这个面积的滚动区不翻，比如横向卡片。
const MIN_SCROLL_AREA = 200000;
// 嵌套列表旁边的空白至少这么宽，才从那里起手划。
const MIN_SWIPE_LANE = 16;

export interface NodeAttrs {
  type?: string;
  text?: string;
  key?: string;
  description?: string;
  bounds?: string;
  checkable?: string;
  checked?: string;
  enabled?: string;
  visible?: string;
  bundleName?: string;
  scrollable?: string;
}

export interface LayoutNode {
  attributes: NodeAttrs;
  children?: LayoutNode[];
}

export class Rect {
  readonly left: number;
  readonly top: number;
  readonly right: number;
  readonly bottom: number;

  constructor(left: number, top: number, right: number, bottom: number) {
    this.left = left;
    this.top = top;
    this.right = right;
    this.bottom = bottom;
  }

  static parse(bounds: string | undefined): Rect {
    const parts = (bounds ?? '').match(/-?\d+/g);
    if (parts === null || parts.length !== 4) {
      return new Rect(0, 0, 0, 0);
    }
    return new Rect(Number(parts[0]), Number(parts[1]), Number(parts[2]), Number(parts[3]));
  }

  get width(): number {
    return this.right - this.left;
  }

  get height(): number {
    return this.bottom - this.top;
  }

  get area(): number {
    return this.width > 0 && this.height > 0 ? this.width * this.height : 0;
  }

  get centerX(): number {
    return Math.floor((this.left + this.right) / 2);
  }

  get centerY(): number {
    return Math.floor((this.top + this.bottom) / 2);
  }

  contains(x: number, y: number): boolean {
    return x >= this.left && x <= this.right && y >= this.top && y <= this.bottom;
  }

  containsRect(other: Rect): boolean {
    return other.left >= this.left && other.right <= this.right && other.top >= this.top && other.bottom <= this.bottom;
  }

  overlapArea(other: Rect): number {
    const width = Math.min(this.right, other.right) - Math.max(this.left, other.left);
    const height = Math.min(this.bottom, other.bottom) - Math.max(this.top, other.top);
    return width > 0 && height > 0 ? width * height : 0;
  }
}

export function clean(text: string | undefined): string {
  return (text ?? '').replace(INVISIBLE_CHARS, '').trim();
}

// 比较文字时用的键：NFKC + 去空格，和 tools/vocab.py 的 key_of 同一个口径。
// 同一个开关在不同版本可能写成「USB 调试」或「USB调试」。
export function keyOf(text: string | undefined): string {
  return clean(text).normalize('NFKC').replace(/\s+/g, '');
}

export class Item {
  readonly type: string;
  readonly text: string;
  readonly description: string;
  readonly rect: Rect;
  readonly checkable: boolean;
  readonly checked: boolean;
  readonly enabled: boolean;
  readonly scrollable: boolean;

  constructor(attrs: NodeAttrs) {
    this.type = attrs.type ?? '';
    this.text = clean(attrs.text);
    this.description = clean(attrs.description);
    this.rect = Rect.parse(attrs.bounds);
    this.checkable = attrs.checkable === 'true';
    this.checked = attrs.checked === 'true';
    this.enabled = attrs.enabled !== 'false';
    this.scrollable = attrs.scrollable === 'true';
  }
}

function isLayer(attrs: NodeAttrs): boolean {
  const type = attrs.type ?? '';
  return (type === 'NavDestination' || type === 'Dialog') && attrs.visible !== 'false' &&
    Rect.parse(attrs.bounds).area > 0;
}

// 页面可能嵌套，同一个节点只收一次。
function collect(node: LayoutNode, out: Item[], seen: Set<NodeAttrs>): void {
  if (!seen.has(node.attributes)) {
    seen.add(node.attributes);
    out.push(new Item(node.attributes));
  }
  for (const child of node.children ?? []) {
    collect(child, out, seen);
  }
}

export class Screen {
  readonly bundle: string;
  readonly windowRect: Rect;
  // 看得见的节点，最上层的排在前面。
  readonly items: Item[] = [];
  // 所有窗口的节点，用来认系统弹窗和协议页。
  readonly allItems: Item[] = [];

  constructor(root: LayoutNode) {
    let app: LayoutNode | undefined = undefined;
    for (const child of root.children ?? []) {
      const bundle = child.attributes.bundleName ?? '';
      if (bundle !== '' && bundle !== SYSTEM_UI) {
        app = child;
        break;
      }
    }
    const scope: LayoutNode = app ?? root;
    this.bundle = scope.attributes.bundleName ?? '';
    this.windowRect = Rect.parse(scope.attributes.bounds);
    collect(root, this.allItems, new Set<NodeAttrs>());

    const found: LayoutNode[] = [];
    const findLayers = (node: LayoutNode): void => {
      if (isLayer(node.attributes)) {
        found.push(node);
      }
      for (const child of node.children ?? []) {
        findLayers(child);
      }
    };
    findLayers(scope);

    const visible: LayoutNode[] = [];
    const visibleRects: Rect[] = [];
    for (let at = found.length - 1; at >= 0; at--) {
      const rect = Rect.parse(found[at].attributes.bounds);
      let covered = 0;
      for (const upper of visibleRects) {
        covered += rect.overlapArea(upper);
      }
      if (covered < rect.area / 2) {
        visible.push(found[at]);
        visibleRects.push(rect);
      }
    }

    const seen = new Set<NodeAttrs>();
    for (const layer of visible) {
      collect(layer, this.items, seen);
    }
    const topLayer: LayoutNode | undefined = visible.length > 0 ? visible[0] : undefined;
    let passedTop = false;
    const visitRest = (node: LayoutNode): void => {
      if (isLayer(node.attributes)) {
        passedTop = passedTop || node === topLayer;
        return;
      }
      const rect = Rect.parse(node.attributes.bounds);
      const insideLayer = visibleRects.some((upper: Rect) => upper.contains(rect.centerX, rect.centerY));
      if ((passedTop || !insideLayer) && !seen.has(node.attributes)) {
        seen.add(node.attributes);
        this.items.push(new Item(node.attributes));
      }
      for (const child of node.children ?? []) {
        visitRest(child);
      }
    };
    visitRest(scope);
  }

  // 找一段文字：完全相等优先，再找以它开头的（行内文字常带逗号和副标题）。
  findText(title: string): Item | undefined {
    const wanted = keyOf(title);
    let loose: Item | undefined = undefined;
    for (const item of this.items) {
      if (item.rect.area <= 0 || item.text === '') {
        continue;
      }
      const key = keyOf(item.text);
      if (key === wanted) {
        return item;
      }
      if (loose === undefined && item.type === 'Text' && key.startsWith(`${wanted},`)) {
        loose = item;
      }
    }
    return loose;
  }

  // 同名文字可能不止一处，比如页面标题和开关行都叫「个性化推荐」。
  findAllText(title: string): Item[] {
    const wanted = keyOf(title);
    return this.items.filter((item: Item) => item.rect.area > 0 && item.text !== '' && keyOf(item.text) === wanted);
  }

  // 该点的位置：行里有开关本体就点本体，整行点中心不一定生效。
  tapTarget(control: Item): Rect {
    let best: Rect = control.rect;
    for (const item of this.items) {
      if ((item.type === 'Toggle' || item.type === 'switch') && item.rect.area > 0 && item.rect.area < best.area &&
        control.rect.containsRect(item.rect)) {
        best = item.rect;
      }
    }
    return best;
  }

  hasText(title: string): boolean {
    return this.findText(title) !== undefined;
  }

  // 第一次使用的协议页。这种页面不替机主同意。
  hasConsent(): boolean {
    for (const item of this.items) {
      if ((item.type === 'Button' || item.type === 'Text') &&
        (item.text === '同意' || item.text === '同意并继续' || item.text === '同意并使用')) {
        return true;
      }
      if (item.text === '隐私声明变更通知') {
        return true;
      }
    }
    return false;
  }

  // 标题所在行的开关。整行可勾选时取行里更小的开关本体，点它最准。
  switchFor(title: Item): Item | undefined {
    const x = title.rect.centerX;
    const y = title.rect.centerY;
    let best: Item | undefined = undefined;
    for (const item of this.items) {
      if (!item.checkable || item.rect.area <= 0 || item.type === 'Checkbox') {
        continue;
      }
      const inRow = item.rect.contains(x, y);
      const beside = Math.abs(item.rect.centerY - y) <= SAME_ROW_DISTANCE && item.rect.left >= title.rect.left &&
        item.rect.left <= title.rect.left + this.windowRect.width;
      if (!inRow && !beside) {
        continue;
      }
      if (best === undefined || item.rect.area < best.rect.area) {
        best = item;
      }
    }
    return best;
  }

  // 拨开关引出的确认按钮。网页里的确认框不是 Dialog 类型，只能按文字认。
  findConfirm(words: string[]): Item | undefined {
    for (const word of words) {
      const found = this.items.find((item: Item) => item.rect.area > 0 && (item.text === word || item.description === word));
      if (found !== undefined) {
        return found;
      }
    }
    return undefined;
  }

  // 文字下方最近的开关，用于华为广告那样的网页。
  switchBelow(title: Item): Item | undefined {
    let best: Item | undefined = undefined;
    for (const item of this.items) {
      if (!item.checkable || item.rect.area <= 0 || item.type !== 'switch' || item.rect.top < title.rect.bottom) {
        continue;
      }
      if (best === undefined || item.rect.top < best.rect.top) {
        best = item;
      }
    }
    return best;
  }

  // 可以上下翻的区域，从大到小。被更大区域包住的不算。
  scrollAreas(): Rect[] {
    const rects: Rect[] = [];
    // 网页节点不标 scrollable，但能滚；网页里的内容要滚到附近才出现在读屏结果里。
    for (const item of this.items) {
      if ((item.scrollable || item.type === 'Web') && item.rect.area >= MIN_SCROLL_AREA) {
        rects.push(item.rect);
      }
    }
    rects.sort((a: Rect, b: Rect) => b.area - a.area);
    const out: Rect[] = [];
    for (const rect of rects) {
      if (!out.some((bigger: Rect) => bigger.containsRect(rect))) {
        out.push(rect);
      }
    }
    return out;
  }

  // 上下划的起点。区域中间被大块的嵌套列表占住时（外屏的主题卡片），
  // 从中间划只会带动嵌套列表，要从它旁边的空白处起手。
  swipeColumn(area: Rect): number {
    let left = area.right;
    let right = area.left;
    for (const item of this.items) {
      const rect = item.rect;
      if (item.scrollable && rect.area >= MIN_SCROLL_AREA && rect.area < area.area && area.containsRect(rect) &&
        rect.contains(area.centerX, rect.centerY)) {
        left = Math.min(left, rect.left);
        right = Math.max(right, rect.right);
      }
    }
    if (left >= right) {
      return area.centerX;
    }
    if (left - area.left >= MIN_SWIPE_LANE) {
      return area.left + Math.floor((left - area.left) / 2);
    }
    if (area.right - right >= MIN_SWIPE_LANE) {
      return right + Math.floor((area.right - right) / 2);
    }
    return area.centerX;
  }

  // 用可见文字做一屏的指纹，翻页后没变就是到底了。
  signature(): string {
    const texts: string[] = [];
    for (const item of this.items) {
      if (item.text !== '') {
        texts.push(item.text);
      }
    }
    return texts.join('|');
  }
}
