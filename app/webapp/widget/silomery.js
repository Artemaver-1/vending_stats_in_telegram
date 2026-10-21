// Силомеры — виджет обслуживания для Scriptable (iPhone).
// Спокойный, пока всё работает; красный, когда силомер стоит; жёлтый, когда нужно
// проверить приёмник оплаты. Обновляется примерно раз в 15 минут.
const TOKEN = "{{TOKEN}}";
const BOT = "{{BOT}}";
const FALLBACK_URL = "{{URL}}";

const RED = new Color("#e5262d");
const YELLOW = new Color("#ffd43b");
const INK = new Color("#111111");
const WHITE = Color.white();
const GREEN = new Color("#30d158");
const CALM = Color.dynamic(new Color("#ffffff"), new Color("#1c1c1e"));
const CALM_TEXT = Color.dynamic(new Color("#111111"), Color.white());
const CALM_HINT = Color.dynamic(new Color("#6e6e73"), new Color("#98989d"));
const CALM_FAINT = Color.dynamic(new Color("#6e6e73", 0.3), new Color("#98989d", 0.3));
const WHITE_FAINT = new Color("#ffffff", 0.35);
const INK_FAINT = new Color("#111111", 0.5);

const FAMILY = config.widgetFamily || "medium";
const SMALL = FAMILY === "small";
const SCALE = SMALL ? 0.8 : FAMILY === "large" || FAMILY === "extraLarge" ? 1.35 : 1;

// Адрес приложения меняется при перезапуске туннеля; бот держит актуальный в описании.
async function baseUrl() {
  if (args.widgetParameter) return args.widgetParameter.trim().replace(/\/+$/, "");
  try {
    const html = await new Request("https://t.me/" + BOT).loadString();
    const found = html.match(/https:\/\/[a-z0-9-]+\.trycloudflare\.com/);
    if (found) {
      Keychain.set("silomery_url", found[0]);
      return found[0];
    }
  } catch (e) {}
  return Keychain.contains("silomery_url") ? Keychain.get("silomery_url") : FALLBACK_URL;
}

async function load() {
  const request = new Request((await baseUrl()) + "/widget/" + TOKEN);
  request.timeoutInterval = 20;
  return await request.loadJSON();
}

const FONTS = {
  black: (size) => Font.blackSystemFont(size),
  heavy: (size) => Font.heavySystemFont(size),
  bold: (size) => Font.boldSystemFont(size),
  semibold: (size) => Font.semiboldSystemFont(size),
  regular: (size) => Font.systemFont(size),
};

function text(stack, value, size, color, weight = "black", lines = 1) {
  const t = stack.addText(value);
  t.font = FONTS[weight](Math.round(size * SCALE));
  t.textColor = color;
  t.lineLimit = lines;
  t.minimumScaleFactor = 0.5;
  return t;
}

function icon(stack, name, size, color) {
  const symbol = SFSymbol.named(name);
  symbol.applyFont(Font.boldSystemFont(size * SCALE));
  const image = stack.addImage(symbol.image);
  image.imageSize = new Size(size * SCALE, size * SCALE);
  image.tintColor = color;
}

function row(parent) {
  const r = parent.addStack();
  r.layoutHorizontally();
  r.centerAlignContent();
  return r;
}

function column(parent) {
  const c = parent.addStack();
  c.layoutVertically();
  return c;
}

// A band of colour across the whole widget. Rows inside end with a spacer, which is
// what stretches the band edge to edge.
function band(widget, color, vertical, horizontal = 16) {
  const b = widget.addStack();
  b.layoutVertically();
  b.backgroundColor = color;
  b.setPadding(vertical * SCALE, horizontal * SCALE, vertical * SCALE, horizontal * SCALE);
  return b;
}

function line(parent, color) {
  const l = parent.addStack();
  l.size = new Size(0, 1);
  l.backgroundColor = color;
  l.addSpacer();
}

function heading(parent, title, color) {
  const r = row(parent);
  icon(r, "exclamationmark.triangle", 15, color);
  r.addSpacer(6 * SCALE);
  text(r, title, 13, color, "heavy");
  r.addSpacer();
}

function checkLine(devices) {
  return ("Проверьте " + devices.join(" и ")).toUpperCase();
}

function taskLine(data) {
  const task = data.next_task;
  if (task) {
    const when = task.overdue ? "Просрочено" : task.when[0].toUpperCase() + task.when.slice(1);
    return when + " · " + task.title;
  }
  if (data.undated_tasks.length) return "Без срока · " + data.undated_tasks[0];
  return "Задач нет";
}

function footer(parent, data, color, faint) {
  const r = row(parent);
  text(r, taskLine(data), 13, color, "semibold");
  r.addSpacer();
  r.addSpacer(8);
  text(r, data.updated, 10, faint, "regular");
}

// The red part: which machine stands, why, and for how many days.
function downSection(parent, down) {
  if (down.length === 1 && SMALL) {
    const d = down[0];
    text(row(parent), d.machine.toUpperCase(), 26, WHITE);
    text(row(parent), d.reason.toUpperCase(), 15, WHITE, "heavy");
    const days = row(parent);
    days.bottomAlignContent();
    text(days, String(d.days), 40, WHITE);
    days.addSpacer(4);
    text(days, d.days_word.toUpperCase(), 15, WHITE, "heavy");
    days.addSpacer();
    return;
  }
  const big = down.length === 1;
  for (const d of down) {
    const r = row(parent);
    const left = column(r);
    text(left, d.machine.toUpperCase(), big ? 32 : 22, WHITE);
    text(left, d.reason.toUpperCase(), big ? 22 : 13, WHITE, big ? "black" : "heavy");
    r.addSpacer();
    r.addSpacer(8);
    const right = column(r);
    right.centerAlignContent();
    text(right, String(d.days), big ? 52 : 26, WHITE);
    text(right, d.days_word.toUpperCase(), big ? 20 : 11, WHITE, big ? "black" : "heavy");
    if (!big) parent.addSpacer(4 * SCALE);
  }
}

// The yellow part: which acceptor to look at, and where.
function checkSection(parent, checks, alone) {
  const big = alone && checks.length === 1;
  for (const c of checks) {
    if (alone) {
      text(row(parent), c.machine.toUpperCase(), big ? 32 : 22, INK);
      text(row(parent), checkLine(c.devices), big ? 20 : 13, INK, "black", 2);
      if (!big) parent.addSpacer(4 * SCALE);
      continue;
    }
    const r = row(parent);
    icon(r, "exclamationmark.triangle", 17, INK);
    r.addSpacer(6 * SCALE);
    text(r, c.machine.toUpperCase(), 20, INK);
    r.addSpacer();
    text(row(parent), checkLine(c.devices), 13, INK, "black", SMALL ? 2 : 1);
  }
}

function calm(w, data) {
  w.backgroundColor = CALM;
  const top = band(w, CALM, 14);
  const head = row(top);
  icon(head, "checkmark.circle.fill", 15, GREEN);
  head.addSpacer(6 * SCALE);
  text(head, "СИЛОМЕРЫ", 13, CALM_HINT, "heavy");
  head.addSpacer();
  top.addSpacer(6 * SCALE);
  text(row(top), "ВСЁ РАБОТАЕТ", 30, CALM_TEXT);
  if (data.machines.length) {
    text(row(top), data.machines.join(" · ") + " на связи", 14, CALM_HINT, "semibold");
  }
  w.addSpacer();
  const bottom = band(w, CALM, 12);
  line(bottom, CALM_FAINT);
  bottom.addSpacer(8 * SCALE);
  footer(bottom, data, CALM_HINT, CALM_HINT);
}

function alarm(w, data) {
  const down = data.down;
  const checks = data.checks;
  if (!down.length) {
    w.backgroundColor = YELLOW;
    const top = band(w, YELLOW, 14);
    heading(top, "НУЖНА ПРОВЕРКА", INK);
    top.addSpacer(6 * SCALE);
    checkSection(top, checks, true);
    w.addSpacer();
    if (!SMALL) footer(band(w, YELLOW, 12), data, INK, INK_FAINT);
    return;
  }

  w.backgroundColor = RED;
  const top = band(w, RED, checks.length ? 10 : 14);
  heading(top, SMALL ? "СРОЧНО" : "СРОЧНО ЧИНИТЬ", WHITE);
  top.addSpacer(4 * SCALE);
  downSection(top, down);
  if (checks.length) {
    checkSection(band(w, YELLOW, 7), checks, false);
    w.addSpacer();
    if (!SMALL) footer(band(w, RED, 8), data, WHITE, WHITE_FAINT);
    return;
  }
  w.addSpacer();
  if (!SMALL) {
    const bottom = band(w, RED, 12);
    line(bottom, WHITE_FAINT);
    bottom.addSpacer(8 * SCALE);
    footer(bottom, data, WHITE, WHITE_FAINT);
  }
}

// The lock screen draws in one tint, so only the words matter there.
function lockScreen(w, data) {
  const lines = data.down.map((d) => "⛔ " + d.machine + " · " + d.days + " " + d.days_word);
  for (const c of data.checks) lines.push("⚠️ " + c.machine + " · " + c.devices.join(", "));
  if (!lines.length) lines.push("✓ Силомеры работают");
  const shown = FAMILY === "accessoryInline" ? lines.slice(0, 1) : lines.slice(0, 3);
  for (const value of shown) {
    const t = w.addText(value);
    t.font = Font.semiboldSystemFont(13);
    t.minimumScaleFactor = 0.6;
    t.lineLimit = 1;
  }
}

function build(data) {
  const w = new ListWidget();
  w.url = "https://t.me/" + BOT;
  w.refreshAfterDate = new Date(Date.now() + 15 * 60 * 1000);
  if (FAMILY.startsWith("accessory")) {
    lockScreen(w, data);
    return w;
  }
  w.setPadding(0, 0, 0, 0);
  if (data.down.length || data.checks.length) alarm(w, data);
  else calm(w, data);
  return w;
}

function offline() {
  const w = new ListWidget();
  w.backgroundColor = CALM;
  w.refreshAfterDate = new Date(Date.now() + 5 * 60 * 1000);
  text(w, "СИЛОМЕРЫ", 13, CALM_HINT, "heavy");
  w.addSpacer(4);
  text(w, "Нет связи с приложением", 16, CALM_TEXT, "bold", 2);
  text(w, "Откройте бота — адрес обновится", 12, CALM_HINT, "regular", 2);
  return w;
}

let widget;
try {
  widget = build(await load());
} catch (e) {
  widget = offline();
}
if (config.runsInWidget) Script.setWidget(widget);
else await widget.presentMedium();
Script.complete();
