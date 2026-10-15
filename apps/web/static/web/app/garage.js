/* Гараж: машины клиента и дневник водителя — «приборная панель».

   Выбор заказчика (редизайн, октябрь 2026). Первый экран отвечает на
   «что пора сделать»: масло — шкалой пробега от прошлой замены до
   следующей (Rivian на Mobbin), документы и резина — тремя плитками
   (Lloyds), пустая плитка — пунктиром «добавить дату». Ниже — добавить
   запись касанием по типу, расходы за месяц или год одной полосой по
   категориям (Revolut) и последние записи дневника.

   Считает всё сервер (`/garage/cars/{id}/summary/`): напоминания, расход
   от полного бака до полного, итоги по категориям. Здесь — только показ:
   вторая копия правил однажды разошлась бы с первой. */

import { CarForm, carLabel, useCars } from "app/cars";
import {
  LoadError, Sheet, Skel, api, ask, bus, call, fmt, html, money, startBooking, toast, useEffect,
  useLoad, useNet, useState,
} from "app/lib";

const KINDS = [
  ["fuel", "Заправка", "fuel"],
  ["oil", "Масло", "drop"],
  ["service", "ТО и ремонт", "wrench"],
  ["tires", "Шиномонтаж", "tire"],
  ["wash", "Мойка", "wash"],
  ["fine", "Штраф", "warn"],
  ["other", "Другое", "box"],
];
const KIND_ICON = Object.fromEntries(KINDS.map(([key, , ico]) => [key, ico]));
// Цвет категории в полосе расходов — по смыслу и одинаковый везде.
const KIND_COLOR = {
  fuel: "var(--accent)", oil: "var(--neon-hot)", service: "var(--warn)", tires: "var(--text-soft)",
  wash: "var(--ok)", fine: "var(--danger)", other: "var(--text-faint)",
};
// Пробег подставляем там, где он важен для напоминаний и расхода.
const NEEDS_MILEAGE = ["fuel", "oil", "service", "tires"];
// Быстрые кнопки «добавить»: то, что пишут чаще всего; остальное — «Ещё».
const QUICK = ["fuel", "wash", "service"];

const km = (n) => fmt.number(n) + " км";
const svg = (name, size) => ({ __html: window.App.icon(name, size || 20) });
// Год — только если не текущий: «16 мая» прошлой и «16 мая» следующей
// замены без года читались бы как одна дата.
const withYear = (iso) => new Date(iso + "T12:00:00").getFullYear() !== new Date().getFullYear();
const day = (iso) => new Date(iso + "T12:00:00")
  .toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: withYear(iso) ? "numeric" : undefined })
  .replace(" г.", "");
const shortDay = (iso) => new Date(iso + "T12:00:00")
  .toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: withYear(iso) ? "numeric" : undefined })
  .replace(" г.", "").replace(".", "");
const todayIso = () => fmt.isoDate();
const days = (n) => fmt.number(Math.abs(n)) + " " + fmt.plural(Math.abs(n), "день", "дня", "дней");
const MONTH_NAMES = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];

export function Garage() {
  const { cars, reload: reloadCars } = useCars();
  const [carId, setCarId] = useState(null);
  const [sheet, setSheet] = useState(null); // {type: "entry"|"car"|"newcar"|"journal"|"cars", ...}

  // Выбранная машина — основная, пока клиент не переключил; удалили
  // выбранную — возвращаемся к основной.
  useEffect(() => {
    if (!cars || !cars.length) return;
    if (!carId || !cars.some((c) => c.id === carId)) setCarId((cars.find((c) => c.is_primary) || cars[0]).id);
  }, [cars]);

  const summary = useLoad(
    () => (carId ? api.get("/garage/cars/" + carId + "/summary/") : Promise.resolve(null)),
    [carId], carId && "garage." + carId,
  );
  const s = summary.data;

  // «Добавить замену» на шкале масла открывает ту же форму дневника.
  useEffect(() => bus.on("garage:add", (kind) => setSheet({ type: "entry", kind })), []);

  function done(message) {
    setSheet(null);
    if (message) toast(message, "ok");
    summary.reload();
    reloadCars();
  }

  let body;
  if (cars === null || (cars.length && !s && !summary.error)) {
    body = html`<${GarageSkeleton} />`;
  } else if (!cars.length) {
    body = html`<div class="stack-lg">
      <section class="card pad invite-book">
        <span class="empty-ico" dangerouslySetInnerHTML=${svg("car", 24)}></span>
        <div>
          <b>Добавьте машину</b>
          <p class="muted">Гараж подскажет, когда менять масло и резину, напомнит про ОСАГО и посчитает расходы и расход топлива.</p>
        </div>
      </section>
      <section class="card pad"><${CarForm} full submitLabel="Добавить машину" onSaved=${() => done("Машина добавлена")} /></section>
    </div>`;
  } else if (summary.error && !s) {
    body = html`<${LoadError} error=${summary.error} onRetry=${summary.reload} />`;
  } else {
    body = html`<div class="stack-lg">
      <${OilGauge} s=${s} />
      <${DocTiles} s=${s} carId=${carId} onSettings=${() => setSheet({ type: "car" })} onDone=${done} />
      <section>
        <h2 class="section-title">Добавить</h2>
        <div class="quick-add">
          ${QUICK.map((kind) => {
            const [, label, ico] = KINDS.find((k) => k[0] === kind);
            return html`<button class="quick-btn" type="button" key=${kind} onClick=${() => setSheet({ type: "entry", kind })}>
              <span dangerouslySetInnerHTML=${svg(ico)}></span>${label}</button>`;
          })}
          <button class="quick-btn" type="button" onClick=${() => setSheet({ type: "entry" })}>
            <span dangerouslySetInnerHTML=${svg("plus")}></span>Ещё</button>
        </div>
      </section>
      <${Stats} s=${s} />
      <${Recent} s=${s} onOpen=${(entry) => setSheet({ type: "entry", entry })}
        onAll=${() => setSheet({ type: "journal" })} />
    </div>`;
  }

  const car = s && s.car;
  return html`<main class="screen">
    <div class="screen-head garage-head">
      ${car ? html`<button class="car-switch" type="button" onClick=${() => setSheet({ type: "cars" })}
          aria-label=${"Машина: " + carLabel(car) + ". Выбрать другую"}>
          <h1>${car.title || car.plate || "Машина"}</h1>
          <span class="chev" dangerouslySetInnerHTML=${svg("down", 20)}></span>
        </button>
        <p>${[car.plate, s.mileage != null ? km(s.mileage) : "пробег не указан"].filter(Boolean).join(" · ")}</p>`
        : html`<h1>Гараж</h1>`}
      ${car && html`<button class="icon-btn garage-settings" type="button" aria-label="Настройки машины"
        onClick=${() => setSheet({ type: "car" })} dangerouslySetInnerHTML=${svg("edit", 20)}></button>`}
    </div>
    ${body}
    ${sheet && sheet.type === "cars" && html`<${Sheet} title="Машины" onClose=${() => setSheet(null)}>
      <div class="list">
        ${(cars || []).map((c) => html`<button class="list-row" type="button" key=${c.id}
          onClick=${() => { setCarId(c.id); setSheet(null); }}>
          <span class="strip-ico" dangerouslySetInnerHTML=${svg("car")}></span>
          <span class="list-body"><b>${c.title || c.plate}</b><span class="muted">${[c.plate, c.is_primary ? "основная" : ""].filter(Boolean).join(" · ")}</span></span>
          ${c.id === carId && html`<span class="chev" style="color:var(--accent)" dangerouslySetInnerHTML=${svg("check", 18)}></span>`}
        </button>`)}
        <button class="list-row" type="button" onClick=${() => setSheet({ type: "newcar" })}>
          <span class="strip-ico" dangerouslySetInnerHTML=${svg("plus")}></span>
          <span class="list-body"><b>Добавить машину</b></span>
        </button>
      </div>
    </${Sheet}>`}
    ${sheet && sheet.type === "entry" && html`<${EntryForm} carId=${carId} mileage=${s && s.mileage}
      kind=${sheet.kind} entry=${sheet.entry} onSaved=${done} onClose=${() => setSheet(null)} />`}
    ${sheet && sheet.type === "car" && s && html`<${Sheet} title=${carLabel(s.car)} onClose=${() => setSheet(null)}>
      <${CarSettings} s=${s} onSaved=${done} />
    </${Sheet}>`}
    ${sheet && sheet.type === "newcar" && html`<${Sheet} title="Новая машина" onClose=${() => setSheet(null)}>
      <${CarForm} full submitLabel="Добавить" onSaved=${(c) => { setCarId(c.id); done("Машина добавлена"); }} />
    </${Sheet}>`}
    ${sheet && sheet.type === "journal" && html`<${Sheet} tall title="Дневник" onClose=${() => setSheet(null)}>
      <${Journal} carId=${carId} onOpen=${(entry) => setSheet({ type: "entry", entry })} />
    </${Sheet}>`}
  </main>`;
}

function GarageSkeleton() {
  return html`<div class="stack-lg" aria-busy="true">
    <div class="card pad stack"><${Skel} w="45%" /><${Skel} h="var(--space-2)" r="var(--radius-pill)" /><${Skel} w="70%" /></div>
    <div class="doc-tiles">${[0, 1, 2].map(() => html`<${Skel} h="var(--space-9)" r="var(--radius-lg)" />`)}</div>
    <${Skel} h="var(--control-lg)" r="var(--radius)" />
    <${Skel} h="var(--space-9)" r="var(--radius-lg)" />
  </div>`;
}

/* ------------------------------------------------------------- масло */

/** Шкала: от прошлой замены до следующей — по пробегу, а без пробега — по
    дате. Что наступит раньше, то и показывает строка «через…». */
function OilGauge({ s }) {
  const r = s.reminders.find((x) => x.kind === "oil");
  if (!r || r.status === "unknown") {
    return html`<section class="card pad gauge is-unknown">
      <div class="gauge-head">
        <span class="strip-ico" dangerouslySetInnerHTML=${svg("drop")}></span>
        <span class="strip-body"><b>Когда меняли масло?</b>
          <span class="muted">Добавьте последнюю замену — подскажем, когда следующая.</span></span>
      </div>
      <button class="btn btn-block" type="button" onClick=${() => bus.emit("garage:add", "oil")}>Добавить замену</button>
    </section>`;
  }

  let share;
  let from;
  let to;
  if (r.left_km != null && r.due_km != null) {
    share = 1 - r.left_km / s.oil_interval_km;
    from = km(r.due_km - s.oil_interval_km);
    to = km(r.due_km);
  } else {
    const total = (new Date(r.due_date) - new Date(r.last_date)) / 86400000;
    share = total > 0 ? 1 - r.left_days / total : 1;
    from = shortDay(r.last_date);
    to = shortDay(r.due_date);
  }
  share = Math.min(1, Math.max(0, share));

  const kmText = r.left_km != null ? (r.left_km < 0 ? "пробег превышен на " + km(-r.left_km) : "через " + km(r.left_km)) : "";
  const dateText = r.left_days < 0 ? "срок прошёл " + day(r.due_date) : "до " + day(r.due_date);
  const head = r.status === "overdue" ? "Пора менять масло" : "Замена масла";
  const badge = r.status === "overdue" ? "пора" : kmText || dateText;
  return html`<section class=${"card pad gauge is-" + r.status}>
    <div class="gauge-head">
      <span class="strip-ico" dangerouslySetInnerHTML=${svg("drop")}></span>
      <span class="strip-body"><b>${head}</b>
        <span class="muted">${kmText ? kmText + " или " + dateText : dateText}${s.mileage == null ? " · укажите пробег — посчитаем и по километрам" : ""}</span></span>
      ${r.status !== "ok" && html`<span class="status is-work">${badge}</span>`}
    </div>
    <div class="gauge-bar" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow=${Math.round(share * 100)}
      aria-label="Пройдено от прошлой замены">
      <i style=${"width:" + Math.round(share * 100) + "%"}></i>
    </div>
    <div class="gauge-scale"><span>прошлая · ${from}</span><span>следующая · ${to}</span></div>
    ${r.status !== "ok" && html`<button class="btn btn-primary btn-block" type="button" onClick=${startBooking}>Записаться на замену</button>`}
  </section>`;
}

/* ------------------------------------------------------- документы */

function DocTiles({ s, carId, onSettings, onDone }) {
  const find = (kind) => s.reminders.find((x) => x.kind === kind);
  const osago = find("osago");
  const inspection = find("inspection");
  const tires = find("tires");

  async function tiresDone() {
    const ok = await call(() => api.post("/garage/cars/" + carId + "/journal/", { kind: "tires", date: todayIso() }));
    if (ok) onDone("Отметили смену резины");
  }

  const docTile = (title, r, until) => {
    if (!until) {
      return html`<button class="doc-tile is-empty" type="button" onClick=${onSettings}>
        <small>${title}</small><span>+ дата</span></button>`;
    }
    const left = r ? r.left_days : null;
    const cls = r && r.status !== "ok" ? " is-" + r.status : "";
    return html`<button class="${"doc-tile" + cls}" type="button" onClick=${onSettings}>
      <small>${title}</small><b>до ${shortDay(until)}</b>
      <span>${left == null ? "" : left < 0 ? "закончился" : left <= 60 ? days(left) : "в порядке"}</span></button>`;
  };

  // Резина: в окне сезона — «пора» жёлтым (решение заказчика) и «уже
  // поменяли» одним касанием; вне окна — просто какой сезон.
  const month = new Date().getMonth();
  const season = month >= 3 && month < 9 ? "летняя" : "зимняя";
  const tireTile = tires
    ? html`<button class=${"doc-tile is-soon"} type="button" onClick=${tiresDone}>
        <small>Резина</small><b>на ${tires.season === "winter" ? "зимнюю" : "летнюю"}</b><span>пора · уже поменял?</span></button>`
    : html`<div class="doc-tile is-quiet"><small>Резина</small><b>${season}</b><span>по сезону</span></div>`;

  return html`<div class="doc-tiles">
    ${docTile("ОСАГО", osago, s.car.osago_until)}
    ${docTile("Техосмотр", inspection, s.car.inspection_until)}
    ${tireTile}
  </div>`;
}

/* ----------------------------------------------------------- расходы */

function Stats({ s }) {
  const [scope, setScope] = useState("month");
  const period = s[scope];
  const total = Number(period.total);
  const now = new Date();
  const title = scope === "month" ? MONTH_NAMES[now.getMonth()] : String(now.getFullYear());
  return html`<section class="card pad stack">
    <div class="row" style="justify-content:space-between">
      <h2 class="section-title" style="margin:0">Расходы · ${title}</h2>
      <div class="seg seg-sm" role="group" aria-label="Период">
        <button type="button" aria-pressed=${String(scope === "month")} onClick=${() => setScope("month")}>Месяц</button>
        <button type="button" aria-pressed=${String(scope === "year")} onClick=${() => setScope("year")}>Год</button>
      </div>
    </div>
    ${total > 0 ? html`
      <div class="spend-total">${money(total)}</div>
      <div class="spend-bar" aria-hidden="true">
        ${period.by_kind.map((k) => html`<i key=${k.kind} style=${"flex:" + Number(k.amount) + ";background:" + KIND_COLOR[k.kind]}></i>`)}
      </div>
      <div class="spend-legend">${period.by_kind.map((k) => html`<div class="spend-row" key=${k.kind}>
        <span class="spend-dot" style=${"background:" + KIND_COLOR[k.kind]}></span>
        <span class="spend-name">${k.kind_display}</span>
        <span class="spend-share">${Math.round(Number(k.amount) / total * 100)}%</span>
        <b>${money(k.amount)}</b>
      </div>`)}</div>`
      : html`<p class="muted">${scope === "month" ? "В этом месяце" : "В этом году"} расходов пока нет — добавляйте заправки и траты, здесь появятся итоги.</p>`}
    <div class="legs">
      <div class="leg"><span class="hint">Средний расход</span>
        <b>${s.fuel.average != null ? String(Number(s.fuel.average)).replace(".", ",") + " л" : "—"}</b>
        <span class="hint">${s.fuel.average != null ? "на 100 км" : "нужны две заправки до полного"}</span></div>
      <div class="leg"><span class="hint">Пробег за ${scope === "month" ? "месяц" : "год"}</span>
        <b>${period.distance != null ? km(period.distance) : "—"}</b></div>
    </div>
  </section>`;
}

/* -------------------------------------------------------------- дневник */

function EntryRow({ entry, onOpen }) {
  const meta = [
    shortDay(entry.date),
    entry.mileage != null ? km(entry.mileage) : "",
    entry.liters != null ? String(Number(entry.liters)).replace(".", ",") + " л" + (entry.full_tank ? "" : " · не полный") : "",
  ].filter(Boolean).join(" · ");
  const clickable = entry.editable;
  return html`<button class="list-row" type="button" disabled=${!clickable} onClick=${() => onOpen(entry)}>
    <span class="strip-ico" dangerouslySetInnerHTML=${svg(KIND_ICON[entry.kind] || "box")}></span>
    <span class="list-body">
      <b>${entry.kind_display}${entry.source === "booking" ? " · у нас" : ""}${entry.note ? " · " + entry.note : ""}</b>
      <span class="muted">${meta}</span>
    </span>
    ${entry.amount != null && html`<b class="list-side">${money(entry.amount)}</b>`}
  </button>`;
}

function Recent({ s, onOpen, onAll }) {
  return html`<section>
    <div class="row" style="justify-content:space-between">
      <h2 class="section-title">Дневник</h2>
      ${s.recent.length > 0 && html`<button class="link-btn" type="button" onClick=${onAll}>Весь</button>`}
    </div>
    ${s.recent.length
      ? html`<div class="list">${s.recent.map((e) => html`<${EntryRow} key=${e.id} entry=${e} onOpen=${onOpen} />`)}</div>`
      : html`<p class="muted">Здесь будут заправки, мойки и ремонт. Замены масла у нас появятся сами.</p>`}
  </section>`;
}

function Journal({ carId, onOpen }) {
  const list = useLoad(() => api.get("/garage/cars/" + carId + "/journal/?limit=300"), [carId], "journal." + carId);
  if (list.error && !list.data) return html`<${LoadError} error=${list.error} onRetry=${list.reload} />`;
  if (!list.data) return html`<div class="stack-sm">${[0, 1, 2, 3].map(() => html`<${Skel} h="var(--control-lg)" r="var(--radius)" />`)}</div>`;
  if (!list.data.length) return html`<p class="muted">Записей пока нет.</p>`;
  return html`<div class="list">${list.data.map((e) => html`<${EntryRow} key=${e.id} entry=${e} onOpen=${onOpen} />`)}</div>`;
}

const toNumber = (value) => (String(value).trim() === "" ? null : String(value).replace(/\s/g, "").replace(",", "."));

/** Новая запись или правка своей — окном снизу: тип касанием, пробег
    подставлен последний известный, кнопка прибита к низу окна. */
function EntryForm({ carId, mileage, kind: presetKind, entry, onSaved, onClose }) {
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
  const net = useNet();

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
    const yes = await ask({ title: "Удалить запись?", confirmLabel: "Удалить", cancelLabel: "Оставить", danger: true });
    if (!yes) return;
    if (await call(() => api.del("/garage/journal/" + entry.id + "/"))) onSaved("Запись удалена");
  }

  return html`<${Sheet} title=${entry ? "Запись дневника" : "Новая запись"} onClose=${onClose}
    actions=${html`
      <button class="btn btn-primary btn-lg" type="button" disabled=${busy || net.offline} onClick=${save}>
        ${net.offline ? "Сохранить — нужна сеть" : busy ? "Сохраняем…" : "Сохранить"}</button>
      ${entry && html`<button class="btn btn-ghost btn-danger" type="button" onClick=${remove}>Удалить запись</button>`}`}>
    <form class="stack" onSubmit=${(e) => { e.preventDefault(); save(); }}>
      <div class="chips" role="group" aria-label="Что добавить">
        ${KINDS.map(([key, label]) => html`<button class="chip" type="button" key=${key}
          aria-pressed=${String(kind === key)} onClick=${() => pickKind(key)}>${label}</button>`)}
      </div>
      <div class="form-pair">
        ${kind === "fuel" && html`<div class="field">
          <label for="e-liters">Литры</label>
          <input id="e-liters" inputmode="decimal" placeholder="Например, 40" value=${liters} onInput=${(e) => setLiters(e.target.value)} />
        </div>`}
        <div class="field">
          <label for="e-amount">Сумма, ₽</label>
          <input id="e-amount" inputmode="decimal" placeholder=${kind === "fuel" ? "Например, 2 600" : "Необязательно"}
            value=${amount} onInput=${(e) => setAmount(e.target.value)} />
        </div>
      </div>
      ${kind === "fuel" && html`<label class="check">
        <input type="checkbox" checked=${full} onChange=${(e) => setFull(e.target.checked)} />
        <span>Полный бак — по нему считается расход</span>
      </label>`}
      <div class="form-pair">
        <div class="field">
          <label for="e-km">Пробег, км</label>
          <input id="e-km" inputmode="numeric" placeholder=${mileage != null ? "Было " + fmt.number(mileage) : "Например, 84 300"} value=${odometer}
            onInput=${(e) => setOdometer(e.target.value)} />
        </div>
        <div class="field">
          <label for="e-date">Дата</label>
          <input id="e-date" type="date" max=${todayIso()} value=${date} onInput=${(e) => setDate(e.target.value)} />
        </div>
      </div>
      <div class="field">
        <label for="e-note">Заметка</label>
        <input id="e-note" maxlength="200" placeholder=${kind === "oil" ? "Где меняли, какое масло" : "Необязательно"}
          value=${note} onInput=${(e) => setNote(e.target.value)} />
      </div>
    </form>
  </${Sheet}>`;
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
      confirmLabel: "Удалить машину", cancelLabel: "Оставить", danger: true,
    });
    if (!yes) return;
    if (await call(() => api.del("/garage/cars/" + car.id + "/"))) onSaved("Машина удалена");
  }

  return html`<div class="stack-lg">
    <section class="stack">
      <h3 class="section-title">Машина</h3>
      <${CarForm} car=${car} full onSaved=${() => onSaved("Сохранено")} />
    </section>
    <form class="stack" onSubmit=${(e) => { e.preventDefault(); saveReminders(); }}>
      <h3 class="section-title">Напоминания</h3>
      <div class="form-pair">
        <div class="field">
          <label for="c-int-km">Масло, каждые км</label>
          <input id="c-int-km" inputmode="numeric" placeholder=${fmt.number(s.oil_interval_km)} value=${intervalKm}
            onInput=${(e) => setIntervalKm(e.target.value)} />
        </div>
        <div class="field">
          <label for="c-int-m">или месяцев</label>
          <input id="c-int-m" inputmode="numeric" placeholder=${String(s.oil_interval_months)} value=${intervalMonths}
            onInput=${(e) => setIntervalMonths(e.target.value)} />
        </div>
      </div>
      <p class="hint">Пусто — как обычно: ${km(s.oil_interval_km)} или ${s.oil_interval_months} мес., что раньше.</p>
      <div class="form-pair">
        <div class="field">
          <label for="c-osago">ОСАГО до</label>
          <input id="c-osago" type="date" value=${osago} onInput=${(e) => setOsago(e.target.value)} />
        </div>
        <div class="field">
          <label for="c-insp">Техосмотр до</label>
          <input id="c-insp" type="date" value=${inspection} onInput=${(e) => setInspection(e.target.value)} />
        </div>
      </div>
      <button class="btn btn-primary btn-block" type="submit" disabled=${busy}>Сохранить напоминания</button>
    </form>
    <div class="list">
      ${!car.is_primary && html`<button class="list-row" type="button" onClick=${makePrimary}>
        <span class="list-body"><b>Сделать основной</b><span class="muted">Её подставим при записи</span></span></button>`}
      <button class="list-row is-danger" type="button" onClick=${remove}>
        <span class="list-body"><b>Удалить машину</b><span class="muted">Записи на сервис останутся в истории</span></span></button>
    </div>
  </div>`;
}
