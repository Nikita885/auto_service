/* Гараж: машины клиента и дневник водителя.

   Один экран: какая машина, что пора сделать (масло, ОСАГО, техосмотр,
   резина), сколько ушло за месяц или год, последние записи и «Добавить» —
   запись в два-три касания, пробег подставлен последний известный.

   Считает всё сервер (`/garage/cars/{id}/summary/`): напоминания, расход
   от полного бака до полного, итоги по категориям. Здесь — только показ:
   вторая копия правил однажды разошлась бы с первой. */

import { CarForm, carLabel, useCars } from "app/cars";
import {
  LoadError, Sheet, api, ask, call, fmt, html, money, startBooking, toast, useEffect, useLoad,
  useState,
} from "app/lib";

const KINDS = [
  ["fuel", "Заправка", "fuel"],
  ["oil", "Масло", "drop"],
  ["service", "ТО и ремонт", "wrench"],
  ["tires", "Шиномонтаж", "car"],
  ["wash", "Мойка", "sun"],
  ["fine", "Штраф", "warn"],
  ["other", "Другое", "box"],
];
const KIND_ICON = Object.fromEntries(KINDS.map(([key, , ico]) => [key, ico]));
// Пробег подставляем там, где он важен для напоминаний и расхода.
const NEEDS_MILEAGE = ["fuel", "oil", "service", "tires"];

const km = (n) => fmt.number(n) + " км";
const svg = (name, size) => ({ __html: window.App.icon(name, size || 20) });
const day = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
const dayYear = (iso) => new Date(iso + "T12:00:00").toLocaleDateString("ru-RU");
const todayIso = () => fmt.isoDate();
const days = (n) => fmt.number(Math.abs(n)) + " " + fmt.plural(Math.abs(n), "день", "дня", "дней");

export function Garage() {
  const { cars, reload: reloadCars } = useCars();
  const [carId, setCarId] = useState(null);
  const [sheet, setSheet] = useState(null); // {type: "entry"|"car"|"newcar"|"journal", ...}

  // Выбранная машина — основная, пока клиент не переключил; удалили
  // выбранную — возвращаемся к основной.
  useEffect(() => {
    if (!cars || !cars.length) return;
    if (!carId || !cars.some((c) => c.id === carId)) setCarId((cars.find((c) => c.is_primary) || cars[0]).id);
  }, [cars]);

  const summary = useLoad(() => (carId ? api.get("/garage/cars/" + carId + "/summary/") : Promise.resolve(null)), [carId]);
  const s = summary.data;

  function done(message) {
    setSheet(null);
    if (message) toast(message, "ok");
    summary.reload();
    reloadCars();
  }

  let body;
  if (cars === null) {
    body = html`<p class="muted center">Загружаем…</p>`;
  } else if (!cars.length) {
    body = html`<div class="stack-lg">
      <div class="empty-state">
        <b>Добавьте машину</b>
        <p>Гараж напомнит о замене масла, страховке и смене резины и посчитает расходы и расход топлива.</p>
      </div>
      <section class="card pad"><${CarForm} full submitLabel="Добавить машину" onSaved=${() => done("Машина добавлена")} /></section>
    </div>`;
  } else if (summary.error && !s) {
    body = html`<${LoadError} error=${summary.error} onRetry=${summary.reload} />`;
  } else if (!s) {
    body = html`<p class="muted center">Загружаем…</p>`;
  } else {
    body = html`<div class="stack-lg">
      ${cars.length > 1 && html`<div class="choice-row" role="tablist" aria-label="Машина">
        ${cars.map((c) => html`<button class="btn btn-sm" type="button" key=${c.id}
          aria-pressed=${String(c.id === carId)} onClick=${() => setCarId(c.id)}>${c.title || c.plate}</button>`)}
      </div>`}
      <${CarHead} s=${s} onSettings=${() => setSheet({ type: "car" })} />
      <${Reminders} s=${s} onAdd=${(kind) => setSheet({ type: "entry", kind })} onDone=${done} carId=${carId} />
      <button class="btn btn-primary btn-block btn-lg" type="button" onClick=${() => setSheet({ type: "entry" })}>
        + Добавить запись</button>
      <${Stats} s=${s} />
      <${Recent} s=${s} onOpen=${(entry) => setSheet({ type: "entry", entry })}
        onAll=${() => setSheet({ type: "journal" })} />
      <button class="btn btn-ghost btn-block" type="button" onClick=${() => setSheet({ type: "newcar" })}>+ Другая машина</button>
    </div>`;
  }

  return html`<main class="screen">
    <div class="screen-head"><h1>Гараж</h1></div>
    ${body}
    ${sheet && sheet.type === "entry" && html`<${Sheet} title=${sheet.entry ? "Запись дневника" : "Новая запись"} onClose=${() => setSheet(null)}>
      <${EntryForm} carId=${carId} mileage=${s && s.mileage} kind=${sheet.kind} entry=${sheet.entry}
        onSaved=${done} />
    </${Sheet}>`}
    ${sheet && sheet.type === "car" && s && html`<${Sheet} title=${carLabel(s.car)} onClose=${() => setSheet(null)}>
      <${CarSettings} s=${s} onSaved=${done} />
    </${Sheet}>`}
    ${sheet && sheet.type === "newcar" && html`<${Sheet} title="Новая машина" onClose=${() => setSheet(null)}>
      <${CarForm} full submitLabel="Добавить" onSaved=${(car) => { setCarId(car.id); done("Машина добавлена"); }} />
    </${Sheet}>`}
    ${sheet && sheet.type === "journal" && html`<${Sheet} title="Дневник" onClose=${() => setSheet(null)}>
      <${Journal} carId=${carId} onOpen=${(entry) => setSheet({ type: "entry", entry })} />
    </${Sheet}>`}
  </main>`;
}

function CarHead({ s, onSettings }) {
  return html`<section class="card pad car-head">
    <div>
      <div class="car-title">${s.car.title || "Автомобиль"}</div>
      <div class="muted">${[s.car.plate, s.mileage != null ? "пробег " + km(s.mileage) : ""].filter(Boolean).join(" · ")}</div>
    </div>
    <button class="icon-btn" type="button" aria-label="Настройки машины" onClick=${onSettings}
      dangerouslySetInnerHTML=${svg("edit", 22)}></button>
  </section>`;
}

/* ---------------------------------------------------------- напоминания */

function Reminders({ s, onAdd, onDone, carId }) {
  // ОСАГО и техосмотр в порядке — молчим: их даты видны в настройках машины.
  const shown = s.reminders.filter((r) => r.kind === "oil" || r.status !== "ok");
  if (!shown.length) return null;

  async function tiresDone() {
    const ok = await call(() => api.post("/garage/cars/" + carId + "/journal/", { kind: "tires", date: todayIso() }));
    if (ok) onDone("Отметили смену резины");
  }

  return html`<div class="stack">${shown.map((r) => {
    let title;
    let text;
    let action = null;
    if (r.kind === "oil" && r.status === "unknown") {
      title = "Когда меняли масло?";
      text = "Добавьте последнюю замену — подскажем, когда следующая.";
      action = html`<button class="btn btn-sm" type="button" onClick=${() => onAdd("oil")}>Добавить замену</button>`;
    } else if (r.kind === "oil") {
      title = r.status === "overdue" ? "Пора менять масло" : "Замена масла";
      const parts = [];
      if (r.left_km != null) parts.push(r.left_km < 0 ? "пробег превышен на " + km(-r.left_km) : "через " + km(r.left_km));
      if (r.left_days != null) parts.push(r.left_days < 0 ? "срок прошёл " + day(r.due_date) : (parts.length ? "или до " : "до ") + day(r.due_date));
      text = parts.join(" ");
      if (r.left_km == null && s.mileage == null) text += ". Укажите пробег — посчитаем и по километрам.";
      if (r.status !== "ok") action = html`<button class="btn btn-sm btn-primary" type="button" onClick=${startBooking}>Записаться</button>`;
    } else if (r.kind === "osago" || r.kind === "inspection") {
      const name = r.kind === "osago" ? "ОСАГО" : "Техосмотр";
      title = r.status === "overdue" ? name + " закончился" : name + " заканчивается";
      text = r.status === "overdue" ? "Срок вышел " + day(r.due_date) : "До " + day(r.due_date) + ", осталось " + days(r.left_days);
    } else if (r.kind === "tires") {
      const season = r.season === "winter" ? "зимнюю" : "летнюю";
      title = r.status === "overdue" ? "Пора на " + season + " резину" : "Скоро менять резину на " + season;
      text = "Сезон с " + day(r.due_date) + ".";
      action = html`<button class="btn btn-sm" type="button" onClick=${tiresDone}>Уже поменяли</button>`;
    }
    return html`<section class=${"card pad reminder is-" + r.status} key=${r.kind}>
      <div class="reminder-text"><b>${title}</b><span class="muted">${text}</span></div>
      ${action}
    </section>`;
  })}</div>`;
}

/* ----------------------------------------------------------- статистика */

function Stats({ s }) {
  const [scope, setScope] = useState("month");
  const period = s[scope];
  const total = Number(period.total);
  return html`<section class="card pad stack">
    <div class="row" style="justify-content:space-between">
      <span class="kicker">Расходы</span>
      <div class="seg seg-sm" role="tablist">
        <button type="button" aria-pressed=${String(scope === "month")} onClick=${() => setScope("month")}>Месяц</button>
        <button type="button" aria-pressed=${String(scope === "year")} onClick=${() => setScope("year")}>Год</button>
      </div>
    </div>
    ${total > 0 ? html`
      <div class="big-number">${money(total)}</div>
      <div class="rank">${period.by_kind.map((k) => html`<div class="rank-row" key=${k.kind}>
        <span class="rank-name">${k.kind_display}</span><span class="rank-value">${money(k.amount)}</span>
        <div class="rank-track"><div class="rank-fill" style=${"width:" + Math.max(2, Math.round(Number(k.amount) / total * 100)) + "%"}></div></div>
      </div>`)}</div>`
      : html`<p class="muted">${scope === "month" ? "В этом месяце" : "В этом году"} расходов пока нет — добавляйте заправки и траты, здесь появятся итоги.</p>`}
    <div class="legs">
      <div class="leg"><span class="hint">Средний расход</span>
        <b>${s.fuel.average != null ? fmt.number(s.fuel.average) + " л" : "—"}</b>
        <span class="hint">${s.fuel.average != null ? "на 100 км" : "нужны две заправки до полного"}</span></div>
      <div class="leg"><span class="hint">Пробег за ${scope === "month" ? "месяц" : "год"}</span>
        <b>${period.distance != null ? km(period.distance) : "—"}</b></div>
    </div>
  </section>`;
}

/* -------------------------------------------------------------- дневник */

function EntryRow({ entry, onOpen }) {
  const meta = [
    dayYear(entry.date),
    entry.mileage != null ? km(entry.mileage) : "",
    entry.liters != null ? fmt.number(entry.liters) + " л" + (entry.full_tank ? "" : " (не полный)") : "",
  ].filter(Boolean).join(" · ");
  const clickable = entry.editable;
  return html`<button class="entry-row" type="button" disabled=${!clickable} onClick=${() => onOpen(entry)}>
    <span class="entry-ico" dangerouslySetInnerHTML=${svg(KIND_ICON[entry.kind] || "box")}></span>
    <span class="entry-body">
      <span>${entry.kind_display}${entry.source === "booking" ? " · у нас" : ""}${entry.note ? " · " + entry.note : ""}</span>
      <span class="hint">${meta}</span>
    </span>
    <span class="entry-amount">${entry.amount != null ? money(entry.amount) : ""}</span>
  </button>`;
}

function Recent({ s, onOpen, onAll }) {
  return html`<section class="card pad stack-sm">
    <span class="kicker">Последние записи</span>
    ${s.recent.length
      ? html`${s.recent.map((e) => html`<${EntryRow} key=${e.id} entry=${e} onOpen=${onOpen} />`)}
          <button class="btn btn-ghost btn-block" type="button" onClick=${onAll}>Весь дневник</button>`
      : html`<p class="muted">Дневник пуст. Добавьте заправку, мойку или ремонт — замены масла у нас появятся здесь сами.</p>`}
  </section>`;
}

function Journal({ carId, onOpen }) {
  const list = useLoad(() => api.get("/garage/cars/" + carId + "/journal/?limit=300"), [carId]);
  if (list.error && !list.data) return html`<${LoadError} error=${list.error} onRetry=${list.reload} />`;
  if (!list.data) return html`<p class="muted">Загружаем…</p>`;
  if (!list.data.length) return html`<p class="muted">Записей пока нет.</p>`;
  return html`<div class="stack-sm">${list.data.map((e) => html`<${EntryRow} key=${e.id} entry=${e} onOpen=${onOpen} />`)}</div>`;
}

const toNumber = (value) => (String(value).trim() === "" ? null : String(value).replace(/\s/g, "").replace(",", "."));

/** Новая запись или правка своей: тип — касанием, остальное подставлено. */
function EntryForm({ carId, mileage, kind: presetKind, entry, onSaved }) {
  const [kind, setKind] = useState(entry ? entry.kind : presetKind || "fuel");
  const [amount, setAmount] = useState(entry && entry.amount != null ? String(Number(entry.amount)) : "");
  const [liters, setLiters] = useState(entry && entry.liters != null ? String(Number(entry.liters)) : "");
  const [full, setFull] = useState(entry ? entry.full_tank : true);
  const [odometer, setOdometer] = useState(entry
    ? (entry.mileage != null ? String(entry.mileage) : "")
    : (mileage != null && NEEDS_MILEAGE.includes(presetKind || "fuel") ? String(mileage) : ""));
  const [date, setDate] = useState(entry ? entry.date : todayIso());
  const [note, setNote] = useState(entry ? entry.note : "");
  const [busy, setBusy] = useState(false);

  function pickKind(next) {
    setKind(next);
    if (!entry && !odometer && mileage != null && NEEDS_MILEAGE.includes(next)) setOdometer(String(mileage));
  }

  async function save() {
    if (kind === "fuel" && !toNumber(liters)) { toast("Сколько литров залили?", "error"); return; }
    const body = {
      kind, date, note: note.trim(), amount: toNumber(amount),
      mileage: toNumber(odometer) == null ? null : Number(toNumber(odometer)),
    };
    if (kind === "fuel") Object.assign(body, { liters: toNumber(liters), full_tank: full });
    setBusy(true);
    const saved = await call(() => (entry
      ? api.patch("/garage/journal/" + entry.id + "/", body)
      : api.post("/garage/cars/" + carId + "/journal/", body)));
    setBusy(false);
    if (saved) onSaved(entry ? "Запись сохранена" : "Добавлено в дневник");
  }

  async function remove() {
    const yes = await ask({ title: "Удалить запись?", confirmLabel: "Удалить", danger: true });
    if (!yes) return;
    if (await call(() => api.del("/garage/journal/" + entry.id + "/"))) onSaved("Запись удалена");
  }

  return html`<form class="stack" onSubmit=${(e) => { e.preventDefault(); save(); }}>
    <div class="choice-row" role="group" aria-label="Что добавить">
      ${KINDS.map(([key, label]) => html`<button class="btn btn-sm" type="button" key=${key}
        aria-pressed=${String(kind === key)} onClick=${() => pickKind(key)}>${label}</button>`)}
    </div>
    ${kind === "fuel" && html`<div class="row" style="flex-wrap:nowrap">
      <div class="field" style="flex:1">
        <label for="e-liters">Литры</label>
        <input id="e-liters" inputmode="decimal" placeholder="40" value=${liters} onInput=${(e) => setLiters(e.target.value)} />
      </div>
      <div class="field" style="flex:1">
        <label for="e-amount">Сумма, ₽</label>
        <input id="e-amount" inputmode="decimal" placeholder="2600" value=${amount} onInput=${(e) => setAmount(e.target.value)} />
      </div>
    </div>`}
    ${kind !== "fuel" && html`<div class="field">
      <label for="e-amount">Сумма, ₽</label>
      <input id="e-amount" inputmode="decimal" placeholder="Необязательно" value=${amount} onInput=${(e) => setAmount(e.target.value)} />
    </div>`}
    <div class="row" style="flex-wrap:nowrap">
      <div class="field" style="flex:1">
        <label for="e-km">Пробег, км</label>
        <input id="e-km" inputmode="numeric" placeholder=${mileage != null ? String(mileage) : "84 300"} value=${odometer}
          onInput=${(e) => setOdometer(e.target.value)} />
      </div>
      <div class="field" style="flex:1">
        <label for="e-date">Дата</label>
        <input id="e-date" type="date" max=${todayIso()} value=${date} onInput=${(e) => setDate(e.target.value)} />
      </div>
    </div>
    ${kind === "fuel" && html`<label class="check">
      <input type="checkbox" checked=${full} onChange=${(e) => setFull(e.target.checked)} />
      <span>Полный бак — по нему считается расход</span>
    </label>`}
    <div class="field">
      <label for="e-note">Заметка</label>
      <input id="e-note" maxlength="200" placeholder=${kind === "oil" ? "Где меняли, какое масло" : "Необязательно"}
        value=${note} onInput=${(e) => setNote(e.target.value)} />
    </div>
    <div class="sticky-actions">
      ${entry && html`<button class="btn btn-danger" type="button" onClick=${remove}>Удалить</button>`}
      <button class="btn btn-primary" type="submit" disabled=${busy}>${busy ? "Сохраняем…" : "Сохранить"}</button>
    </div>
  </form>`;
}

/* --------------------------------------------------------- настройки */

/** Машина: название, номер, пробег — и всё, от чего зависят напоминания. */
function CarSettings({ s, onSaved }) {
  const car = s.car;
  const [intervalKm, setIntervalKm] = useState(car.oil_interval_km != null ? String(car.oil_interval_km) : "");
  const [intervalMonths, setIntervalMonths] = useState(car.oil_interval_months != null ? String(car.oil_interval_months) : "");
  const [osago, setOsago] = useState(car.osago_until || "");
  const [inspection, setInspection] = useState(car.inspection_until || "");
  const [busy, setBusy] = useState(false);

  async function saveReminders() {
    setBusy(true);
    const ok = await call(() => api.patch("/garage/cars/" + car.id + "/", {
      oil_interval_km: toNumber(intervalKm) == null ? null : Number(toNumber(intervalKm)),
      oil_interval_months: toNumber(intervalMonths) == null ? null : Number(toNumber(intervalMonths)),
      osago_until: osago || null,
      inspection_until: inspection || null,
    }));
    setBusy(false);
    if (ok) onSaved("Напоминания сохранены");
  }

  async function makePrimary() {
    if (await call(() => api.post("/garage/cars/" + car.id + "/make-primary/", {}))) onSaved("Теперь эта машина основная");
  }

  async function remove() {
    const yes = await ask({
      title: "Удалить " + carLabel(car) + "?",
      text: "Машина и её дневник пропадут из гаража. Прошлые записи на сервис останутся в истории.",
      confirmLabel: "Удалить", danger: true,
    });
    if (!yes) return;
    if (await call(() => api.del("/garage/cars/" + car.id + "/"))) onSaved("Машина удалена");
  }

  return html`<div class="stack-lg">
    <section class="card pad"><${CarForm} car=${car} full onSaved=${() => onSaved("Сохранено")} /></section>
    <form class="card pad stack" onSubmit=${(e) => { e.preventDefault(); saveReminders(); }}>
      <span class="kicker">Напоминания</span>
      <div class="row" style="flex-wrap:nowrap">
        <div class="field" style="flex:1">
          <label for="c-int-km">Масло, каждые км</label>
          <input id="c-int-km" inputmode="numeric" placeholder=${String(s.oil_interval_km)} value=${intervalKm}
            onInput=${(e) => setIntervalKm(e.target.value)} />
        </div>
        <div class="field" style="flex:1">
          <label for="c-int-m">или месяцев</label>
          <input id="c-int-m" inputmode="numeric" placeholder=${String(s.oil_interval_months)} value=${intervalMonths}
            onInput=${(e) => setIntervalMonths(e.target.value)} />
        </div>
      </div>
      <p class="hint">Пусто — по умолчанию: ${km(s.oil_interval_km)} или ${s.oil_interval_months} мес., что раньше.</p>
      <div class="row" style="flex-wrap:nowrap">
        <div class="field" style="flex:1">
          <label for="c-osago">ОСАГО до</label>
          <input id="c-osago" type="date" value=${osago} onInput=${(e) => setOsago(e.target.value)} />
        </div>
        <div class="field" style="flex:1">
          <label for="c-insp">Техосмотр до</label>
          <input id="c-insp" type="date" value=${inspection} onInput=${(e) => setInspection(e.target.value)} />
        </div>
      </div>
      <button class="btn btn-primary btn-block" type="submit" disabled=${busy}>Сохранить напоминания</button>
    </form>
    ${!car.is_primary && html`<button class="btn btn-block" type="button" onClick=${makePrimary}>Сделать основной</button>`}
    <button class="btn btn-ghost btn-danger btn-block" type="button" onClick=${remove}>Удалить машину</button>
  </div>`;
}
