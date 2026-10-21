// Силомеры — виджет обслуживания для Scriptable (iPhone).
// Показывает, что сломано и какая задача следующая. Обновляется примерно раз в 15 минут.
const TOKEN = "{{TOKEN}}";
const BOT = "{{BOT}}";
const FALLBACK_URL = "{{URL}}";

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

function line(widget, text, size, color, bold) {
  const t = widget.addText(text);
  t.font = bold ? Font.heavySystemFont(size) : Font.systemFont(size);
  t.textColor = color;
  t.minimumScaleFactor = 0.6;
  return t;
}

function build(data) {
  const w = new ListWidget();
  w.url = "https://t.me/" + BOT;
  w.refreshAfterDate = new Date(Date.now() + 15 * 60 * 1000);
  const white = Color.white();
  const down = data.alerts.filter((a) => a.level === "down");
  const payments = data.alerts.filter((a) => a.level === "payment");

  if (down.length) {
    const g = new LinearGradient();
    g.colors = [new Color("#e5484d"), new Color("#8f1b20")];
    g.locations = [0, 1];
    w.backgroundGradient = g;
    line(w, "🚨 ЧИНИТЬ СРОЧНО!", 18, white, true);
    w.addSpacer(4);
    down.forEach((a) => line(w, a.text, 13, white, true));
    payments.forEach((a) => line(w, "⚠️ " + a.text, 12, white, false));
  } else if (payments.length) {
    const g = new LinearGradient();
    g.colors = [new Color("#f5a524"), new Color("#b36b00")];
    g.locations = [0, 1];
    w.backgroundGradient = g;
    line(w, "⚠️ Проверить оплату", 17, white, true);
    w.addSpacer(4);
    payments.forEach((a) => line(w, a.text, 13, white, false));
  } else {
    w.backgroundColor = new Color("#1c2a4a");
    line(w, "✅ Всё работает", 16, white, true);
  }

  w.addSpacer();
  const task = data.next_task;
  if (task) {
    line(w, (task.overdue ? "⏰ Просрочено: " : "Следующая: ") + task.when, 12, white, true);
    line(w, task.title, 12, white, false);
  } else if (data.undated_tasks.length) {
    line(w, "Без срока: " + data.undated_tasks[0], 12, white, false);
  } else {
    line(w, "Задач нет 🎉", 12, white, false);
  }
  const footer = w.addText("обновлено " + data.updated);
  footer.font = Font.systemFont(9);
  footer.textColor = new Color("#ffffff", 0.6);
  return w;
}

let widget;
try {
  widget = build(await load());
} catch (e) {
  widget = new ListWidget();
  widget.backgroundColor = new Color("#333333");
  line(widget, "Силомеры", 15, Color.white(), true);
  line(widget, "Нет связи с приложением. Откройте бота — адрес обновится.", 11, Color.white(), false);
  widget.refreshAfterDate = new Date(Date.now() + 5 * 60 * 1000);
}
if (config.runsInWidget) Script.setWidget(widget);
else await widget.presentMedium();
Script.complete();
