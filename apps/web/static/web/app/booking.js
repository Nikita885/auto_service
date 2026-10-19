/* Мастер записи: адрес → категория → услуга → время → машина и подтверждение.

   Открывается окном снизу на «Главной» (`BookingWizard` в `Sheet`).
   Черновик живёт на сервере, поэтому окно можно закрыть в любой момент:
   «Главная» покажет «Продолжить запись», и мастер откроется на том же
   шаге с тем же таймером.

   Шаги идут по порядку, сверху видно, что уже выбрано, и на любой
   пройденный шаг можно вернуться касанием: сервер это разрешает и сам
   сбрасывает то, что зависит от изменённого (другой адрес — заново
   категория, услуга и время; другая категория — заново услуга). Цен
   клиент не видит нигде: ни в списках, ни в подтверждении. Вперёд — только по порядку: какой шаг
   следующий, говорит сервер (`next_action`); своего конечного автомата
   здесь нет — вторая копия правил однажды разошлась бы с первой. Таймер
   тоже серверный: `seconds_left` при каждом ответе, локально только
   тикаем до следующего. */

import { AssistantChat } from "app/assistant";
import { CarPicker, carLabel } from "app/cars";
import {
  CONFIG, InfoRow, Skel, api, ask, call, errorText, fmt, html, toast, useEffect, useRef, useState,
  visitTime,
} from "app/lib";

const GONE = ["draft_expired", "draft_closed"];

// Обещание клиенту — слово в слово решение заказчика (октябрь 2026):
// мастер точки перезванивает в течение 30 минут в рабочее время, заявки
// вне рабочих часов — утром.
export const CALLBACK_TEXT = "Мастер позвонит и поможет выбрать: в рабочее время — в течение 30 минут, "
  + "вне рабочих часов — утром";

/** Шаги по порядку: ключ вида, действие сервера и подпись чипа. */
const STEPS = [
  ["point", "select_point", "Адрес"],
  ["category", "select_category", "Категория"],
  ["service", "select_service", "Услуга"],
  ["slot", "select_slot", "Время"],
  ["confirm", "confirm", "Машина"],
];
const viewOf = (action) => (STEPS.find((s) => s[1] === action) || STEPS[0])[0];

/** Значок категории по её виду — тому же, что попадает в дневник. */
const KIND_ICON = { oil: "drop", tires: "tire", wash: "wash", service: "wrench", other: "list" };
export const kindIcon = (kind) => KIND_ICON[kind] || "list";
const indexOf = (view) => STEPS.findIndex((s) => s[0] === view);

/** Весь сценарий записи. `onClose` — закрыть окно (черновик остаётся),
    `onBooked(booking)` — запись создана. */
export function BookingWizard({ onClose, onBooked }) {
  const [draft, setDraft] = useState(undefined); // undefined — грузим, null — не вышло начать
  const [view, setView] = useState(null);
  const [created, setCreated] = useState(null);
  const [expired, setExpired] = useState(false);
  const [busy, setBusy] = useState(false);
  // Подсказчик: доступен ли на этой точке, с какого шага открыт, разговор.
  const [helper, setHelper] = useState(false);
  const [helperFrom, setHelperFrom] = useState(null);
  const [chat, setChat] = useState(null);
  // Предложение, которое не успели выбрать: пять минут вышли — после
  // «Начать заново» проводим его сами, а не просим выбирать снова.
  const pending = useRef(null);

  function accept(next) {
    setDraft(next);
    setView(viewOf(next.next_action));
  }

  /** Открыли окно — продолжаем живой черновик или начинаем новый. */
  async function begin(restart) {
    setBusy(true);
    try {
      const next = await api.post("/bookings/drafts/", { restart: Boolean(restart) });
      accept(next);
      setExpired(false);
      setCreated(null);
      return next;
    } catch (err) {
      setDraft(null);
      toast(errorText(err), "error");
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => { begin(false); }, []);

  // Кнопку подсказчика показываем, только если сервер говорит «доступен»:
  // провайдер настроен, бюджет не выбран, вопросы на сегодня остались.
  // Не вышло спросить — просто без кнопки: запись работает и так.
  const pointId = draft && draft.service_point && draft.service_point.id;
  useEffect(() => {
    setHelper(false);
    if (!pointId) return;
    api.get("/assistant/?service_point=" + pointId)
      .then((s) => setHelper(Boolean(s && s.available)), () => setHelper(false));
  }, [pointId]);

  function openHelper() {
    setHelperFrom(view);
    setView("assistant");
  }

  /** Провести предложение подсказчика обычными шагами черновика.
      `from` — черновик, с которого начинаем; `point` — сначала выбрать
      адрес (после «Начать заново» черновик пустой). */
  async function applySuggestion(s, from = draft, point = null) {
    if (busy && !point) return;
    setBusy(true);
    let current = from;
    const post = async (path, body) => {
      current = await api.post("/bookings/drafts/" + current.id + "/" + path + "/", body);
    };
    try {
      if (point) await post("select-point", { service_point_id: point });
      if (!current.service_category || current.service_category.id !== s.category.id) {
        await post("select-category", { category_id: s.category.id });
      }
      if (s.service) await post("select-service", { service_id: s.service.id });
      else if (s.on_site) await post("select-service", { on_site: true });
      // Предложена только категория — откроется её список услуг.
      accept(current);
    } catch (err) {
      if (GONE.includes(err.code)) {
        pending.current = { s, point: point || from.service_point.id };
        setExpired(true);
      } else {
        toast(errorText(err), "error");
        reload();
      }
    } finally {
      setBusy(false);
    }
  }

  async function restart() {
    const wanted = pending.current;
    pending.current = null;
    const next = await begin(true);
    if (next && wanted) await applySuggestion(wanted.s, next, wanted.point);
  }

  async function reload() {
    try {
      const current = await api.get("/bookings/drafts/current/");
      if (current) accept(current);
      else setExpired(true);
    } catch (err) {
      toast(errorText(err), "error");
    }
  }

  /** Любой шаг: отправить, принять новое состояние, пережить «время вышло». */
  async function step(path, body) {
    if (busy) return undefined;
    setBusy(true);
    try {
      const next = await api.post("/bookings/drafts/" + draft.id + "/" + path + "/", body || {});
      accept(next);
      return next;
    } catch (err) {
      if (GONE.includes(err.code)) {
        setExpired(true);
      } else {
        toast(errorText(err), "error");
        // Слот заняли или услугу разобрали — черновик жив, перечитываем его.
        if (err.code === "slot_taken" || err.code === "service_out_of_stock") reload();
      }
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  async function confirm(comment, carId) {
    if (busy) return;
    setBusy(true);
    try {
      const booking = await api.post("/bookings/drafts/" + draft.id + "/confirm/", {
        comment, car_id: carId || null,
      });
      setCreated(booking);
      onBooked(booking);
    } catch (err) {
      if (GONE.includes(err.code)) setExpired(true);
      else {
        toast(errorText(err), "error");
        // Машину удалили на другом устройстве — черновик жив, выбор
        // перечитается; остальное (слот, услуга) — перечитываем черновик.
        if (err.code !== "car_not_found") reload();
      }
    } finally {
      setBusy(false);
    }
  }

  async function drop() {
    const yes = await ask({
      title: "Прервать запись?",
      text: "Выбранное время сразу освободится.",
      confirmLabel: "Прервать", cancelLabel: "Продолжить запись", danger: true,
    });
    if (!yes) return;
    await call(() => api.post("/bookings/drafts/" + draft.id + "/cancel/", {}));
    onClose();
  }

  if (created) return html`<${Created} booking=${created} onDone=${onClose} />`;
  if (expired) {
    return html`<div class="empty-state">
      <span class="empty-ico" dangerouslySetInnerHTML=${{ __html: window.App.icon("clock", 24) }}></span>
      <b>Пять минут вышли</b>
      <p>Выбранное время освободилось. Начните заново — это быстро.</p>
      <button class="btn btn-primary btn-lg" type="button" disabled=${busy} onClick=${restart}>Начать заново</button>
    </div>`;
  }
  if (draft === undefined) return html`<${WizardSkeleton} />`;
  if (draft === null) {
    return html`<div class="empty-state">
      <b>Не получилось начать запись</b>
      <p>Попробуйте ещё раз или запишитесь по телефону ${CONFIG.phone}.</p>
      <button class="btn btn-primary" type="button" disabled=${busy} onClick=${() => begin(false)}>Повторить</button>
    </div>`;
  }

  const point = draft.service_point;
  let content;
  const onHelp = helper ? openHelper : null;
  if (view === "point") content = html`<${PointStep} draft=${draft} busy=${busy} step=${step} />`;
  else if (view === "category") content = html`<${CategoryStep} draft=${draft} busy=${busy} step=${step} onHelp=${onHelp} />`;
  else if (view === "service") content = html`<${ServiceStep} draft=${draft} busy=${busy} step=${step} onHelp=${onHelp} />`;
  else if (view === "assistant") {
    content = html`<${AssistantChat} pointId=${point.id} state=${chat} setState=${setChat} busy=${busy}
      callbackText=${CALLBACK_TEXT} onApply=${(s) => applySuggestion(s)}
      onBack=${() => setView(helperFrom || "category")} />`;
  } else if (view === "slot") {
    content = html`<${SlotPicker} pointId=${point.id} zone=${point.timezone} pointName=${point.name}
      initial=${draft.slot_start} busy=${busy} actionLabel="Дальше"
      onPick=${(startAt) => step("select-slot", { start_at: startAt })} />`;
  } else content = html`<${ConfirmStep} draft=${draft} busy=${busy} confirm=${confirm} />`;

  return html`<div class="wizard">
    <${StepChips} draft=${draft} view=${view === "assistant" ? helperFrom : view} onPick=${setView}
      onExpire=${() => setExpired(true)} />
    ${content}
    <button class="link-btn wizard-drop" type="button" onClick=${drop}>Прервать запись</button>
  </div>`;
}

function WizardSkeleton() {
  return html`<div class="stack" aria-busy="true">
    <div class="row"><${Skel} w="60%" h="var(--control-sm)" r="var(--radius-pill)" /><span class="spacer"></span><${Skel} w="var(--control-lg)" h="var(--control-sm)" r="var(--radius-pill)" /></div>
    <${Skel} w="40%" h="var(--fs-h3)" />
    <${Skel} h="var(--control-lg)" r="var(--radius)" />
    <${Skel} h="var(--control-lg)" r="var(--radius)" />
  </div>`;
}

/** Шаги чипами: пройденный показывает выбранное и открывается касанием,
    текущий подсвечен, будущие недоступны. Справа — таймер. */
function StepChips({ draft, view, onPick, onExpire }) {
  const reached = indexOf(viewOf(draft.next_action));
  const value = {
    point: draft.service_point && draft.service_point.name,
    category: draft.service_category && draft.service_category.name,
    service: draft.on_site ? "На месте" : draft.service && draft.service.name,
    slot: draft.slot_start && visitTime(draft.slot_start, draft.service_point.timezone),
    confirm: null,
  };
  const at = indexOf(view);
  return html`<div class="wizard-top">
    <div class="wizard-head">
      <span class="kicker">Шаг ${at + 1} из ${STEPS.length}</span>
      <${Timer} seconds=${draft.seconds_left} stamp=${draft.id + draft.step} onExpire=${onExpire} />
    </div>
    <nav class="step-chips" aria-label="Шаги записи">
      ${STEPS.map(([key, , label], i) => {
        const current = key === view;
        const done = i < reached || (i <= reached && value[key]);
        return html`<button type="button" key=${key} class=${"step-chip" + (current ? " is-current" : "") + (done ? " is-done" : "")}
          disabled=${i > reached} aria-current=${current ? "step" : null}
          aria-label=${label + (done && value[key] ? ": " + value[key] : "")} onClick=${() => onPick(key)}>
          <small>${label}</small>
          <span>${(done && value[key]) || (current ? "выбираем" : "—")}</span>
        </button>`;
      })}
    </nav>
  </div>`;
}

export function Timer({ seconds, stamp, onExpire }) {
  const deadline = useRef(Date.now() + seconds * 1000);
  const [left, setLeft] = useState(seconds);

  // Сервер присылает остаток на каждом шаге — сверяем часы по нему.
  useEffect(() => {
    deadline.current = Date.now() + seconds * 1000;
    setLeft(seconds);
  }, [stamp, seconds]);

  useEffect(() => {
    const t = setInterval(() => {
      const s = Math.max(0, Math.round((deadline.current - Date.now()) / 1000));
      setLeft(s);
      if (s === 0) { clearInterval(t); if (onExpire) onExpire(); }
    }, 1000);
    return () => clearInterval(t);
  }, [stamp]);

  return html`<span class=${"timer" + (left <= 60 ? " low" : "")} role="timer"
    aria-label=${"На запись осталось " + fmt.clock(left)}>${fmt.clock(left)}</span>`;
}

function Choice({ selected, disabled, onClick, title, meta, side, icon }) {
  return html`<button class="choice" type="button" aria-pressed=${String(Boolean(selected))} disabled=${disabled} onClick=${onClick}>
    ${icon && html`<span class="choice-ico" aria-hidden="true" dangerouslySetInnerHTML=${{ __html: window.App.icon(icon, 20) }}></span>`}
    <span class="choice-body">
      <span class="choice-title">${title}</span>
      ${meta && html`<span class="choice-meta">${meta}</span>`}
    </span>
    ${side}
    <span class="choice-mark" aria-hidden="true" dangerouslySetInnerHTML=${{ __html: window.App.icon("check", 16) }}></span>
  </button>`;
}

const hours = (p) => p.opens_at.slice(0, 5) + "–" + p.closes_at.slice(0, 5);

function PointStep({ draft, busy, step }) {
  const [points, setPoints] = useState(null);
  useEffect(() => { call(() => api.get("/service-points/")).then((p) => setPoints(p || [])); }, []);
  const chosen = draft.service_point && draft.service_point.id;
  return html`<section class="stack">
    <h3 class="step-title">Куда приедете?</h3>
    ${!points ? html`<${Skel} h="var(--control-lg)" r="var(--radius)" /><${Skel} h="var(--control-lg)" r="var(--radius)" />`
      : !points.length ? html`<p class="muted">Адресов пока нет. Запишитесь по телефону ${CONFIG.phone}.</p>`
      : html`<div class="stack-sm">${points.map((p) => html`<${Choice} key=${p.id} selected=${p.id === chosen} disabled=${busy}
          title=${p.name} meta=${p.address + " · " + hours(p)}
          onClick=${() => step("select-point", { service_point_id: p.id })} />`)}</div>`}
    ${chosen && html`<p class="hint">Другой адрес — услугу и время выберете заново: на нём свои услуги и своё расписание.</p>`}
  </section>`;
}

/** Что входит в категорию — первые услуги по названию, без цен. */
function categoryMeta(category) {
  const names = category.services.map((s) => s.name);
  if (!names.length) return "Мастер подберёт на месте";
  const shown = names.slice(0, 2).join(" · ");
  return names.length > 2 ? shown + " и ещё " + (names.length - 2) : shown;
}

/** «Помочь с выбором» — открывает подсказчика, если он доступен. */
function HelpChoice({ onHelp, busy }) {
  if (!onHelp) return null;
  return html`<${Choice} disabled=${busy} icon="chat" title="Помочь с выбором"
    meta="Опишите, что с машиной, — подскажем услугу" onClick=${onHelp} />`;
}

function CategoryStep({ draft, busy, step, onHelp }) {
  const [categories, setCategories] = useState(null);
  useEffect(() => {
    call(() => api.get("/service-points/" + draft.service_point.id + "/categories/"))
      .then((rows) => setCategories(rows || []));
  }, [draft.service_point.id]);
  const chosen = draft.service_category && draft.service_category.id;
  return html`<section class="stack">
    <h3 class="step-title">Что нужно сделать?</h3>
    ${!categories ? html`<${Skel} h="var(--control-lg)" r="var(--radius)" /><${Skel} h="var(--control-lg)" r="var(--radius)" />`
      : !categories.length ? html`<p class="muted">На этом адресе сейчас не записаться — выберите другой или позвоните: ${CONFIG.phone}.</p>`
      : html`<div class="stack-sm">${categories.map((c) => html`<${Choice} key=${c.id} selected=${c.id === chosen}
          disabled=${busy} icon=${kindIcon(c.journal_kind)} title=${c.name} meta=${categoryMeta(c)}
          onClick=${() => step("select-category", { category_id: c.id })} />`)}
          <${HelpChoice} onHelp=${onHelp} busy=${busy} /></div>`}
    ${chosen && html`<p class="hint">Другая категория — услугу выберете заново, время останется за вами.</p>`}
  </section>`;
}

function ServiceStep({ draft, busy, step, onHelp }) {
  const category = draft.service_category;
  const [services, setServices] = useState(null);
  useEffect(() => {
    setServices(null);
    call(() => api.get("/service-points/" + draft.service_point.id + "/services/?category=" + category.id))
      .then((rows) => setServices(rows || []));
  }, [category.id]);
  const chosen = draft.service && draft.service.id;
  return html`<section class="stack">
    <h3 class="step-title">${category.name}: что именно?</h3>
    ${!services ? html`<${Skel} h="var(--control-lg)" r="var(--radius)" /><${Skel} h="var(--control-lg)" r="var(--radius)" />`
      : html`<div class="stack-sm">
          ${services.map((s) => html`<${Choice} key=${s.id} selected=${s.id === chosen} disabled=${busy}
            title=${s.name} meta=${s.description} onClick=${() => step("select-service", { service_id: s.id })} />`)}
          ${category.allow_on_site && html`<${Choice} selected=${draft.on_site} disabled=${busy}
            title="Не знаю — подберите на месте" meta=${CALLBACK_TEXT}
            onClick=${() => step("select-service", { on_site: true })} />`}
          <${HelpChoice} onHelp=${onHelp} busy=${busy} />
        </div>`}
    ${services && !services.length && html`<p class="hint">${category.allow_on_site
      ? "Сейчас здесь нечего выбрать — нажмите «Подберите на месте» или выберите другой адрес."
      : "Сейчас здесь нечего выбрать — выберите другую категорию или адрес."}</p>`}
  </section>`;
}

const DOW = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];
const MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];
/** Группы времени по часам точки: искать глазами проще, чем по сетке из 24. */
const PARTS = [["Утро", 0, 12], ["День", 12, 17], ["Вечер", 17, 24]];

/** Свободное время точки: дни лентой, время группами, кнопка с выбором.

    Общий для шага записи и для переноса — у них одна и та же точка, одна
    и та же сетка и одно правило свободного поста. `initial` — уже
    выбранное время (вернулись на шаг): открываемся на его дне. */
export function SlotPicker({ pointId, zone, pointName, busy, actionLabel, onPick, initial }) {
  const [days, setDays] = useState(null);
  const [day, setDay] = useState(null);
  const [slots, setSlots] = useState(null);
  const [picked, setPicked] = useState(initial || null);

  useEffect(() => {
    call(() => api.get("/service-points/" + pointId + "/slots/")).then((data) => {
      const list = (data && data.available_days) || [];
      setDays(list);
      const initialDay = initial && localDay(initial, zone);
      setDay(list.includes(initialDay) ? initialDay : list[0] || null);
    });
  }, [pointId]);

  useEffect(() => {
    if (!day) return;
    setSlots(null);
    call(() => api.get("/service-points/" + pointId + "/slots/?date=" + day)).then((data) => {
      setSlots((data && data.slots) || []);
    });
  }, [day]);

  if (!days) {
    return html`<div class="stack" aria-busy="true"><${Skel} h="var(--control-lg)" r="var(--radius)" /><${Skel} h="var(--space-9)" r="var(--radius)" /></div>`;
  }
  if (!days.length) return html`<p class="muted">Свободного времени в ближайшие дни нет. Позвоните нам: ${CONFIG.phone}.</p>`;

  const today = localDay(new Date().toISOString(), zone);
  const dayDate = (d) => new Date(d + "T12:00:00");
  const month = day ? MONTHS[dayDate(day).getMonth()] : "";

  return html`<section class="stack">
    <h3 class="step-title">Когда удобно?</h3>
    <span class="label">${month}</span>
    <div class="days" role="listbox" aria-label="День">
      ${days.map((d) => {
        const date = dayDate(d);
        const label = d === today ? "сег" : DOW[date.getDay()];
        return html`<button class="day" type="button" key=${d} role="option" aria-selected=${String(d === day)}
          aria-pressed=${String(d === day)} onClick=${() => setDay(d)}>
          <small>${label}</small><b>${date.getDate()}</b>
        </button>`;
      })}
    </div>
    ${slots === null ? html`<${Skel} h="var(--space-9)" r="var(--radius)" />` : slots.length === 0
      ? html`<p class="muted">На этот день всё занято — выберите другой.</p>`
      : PARTS.map(([title, from, to]) => {
          const group = slots.filter((s) => { const h = Number(s.local_time.slice(0, 2)); return h >= from && h < to; });
          if (!group.length) return null;
          return html`<div class="slot-group" key=${title}>
            <span class="label">${title} · ${group.length}</span>
            <div class="slots">
              ${group.map((s) => html`<button class="slot-btn" type="button" key=${s.start_at}
                aria-pressed=${String(sameMoment(picked, s.start_at))} onClick=${() => setPicked(s.start_at)}>${s.local_time}</button>`)}
            </div>
          </div>`;
        })}
    <p class="hint">Время — по адресу «${pointName}».</p>
    <div class="sticky-actions">
      <button class="btn btn-primary btn-lg" type="button" disabled=${!picked || busy}
        onClick=${() => onPick(picked)}>
        ${picked ? actionLabel + " · " + visitTime(picked, zone) : "Выберите время"}
      </button>
    </div>
  </section>`;
}

/** День в календаре точки: «2026-10-14». */
function localDay(iso, zone) {
  try { return new Date(iso).toLocaleDateString("en-CA", { timeZone: zone || undefined }); } catch (e) { return iso.slice(0, 10); }
}
const sameMoment = (a, b) => Boolean(a && b) && new Date(a).getTime() === new Date(b).getTime();

function ConfirmStep({ draft, busy, confirm }) {
  const [comment, setComment] = useState("");
  const [carId, setCarId] = useState(null);
  const point = draft.service_point;
  return html`<section class="stack">
    <h3 class="step-title">Проверьте и подтвердите</h3>
    <div class="card pad info-list">
      <${InfoRow} icon="calendar" label="Когда">${visitTime(draft.slot_start, point.timezone)}</${InfoRow}>
      <${InfoRow} icon="pin" label=${point.name}>${point.address}</${InfoRow}>
      <${InfoRow} icon=${kindIcon(draft.service_category.journal_kind)} label=${draft.service_category.name}>${draft.on_site ? "Подберём на месте — мастер позвонит" : draft.service.name}</${InfoRow}>
    </div>
    <span class="label">Какую машину привезёте</span>
    <${CarPicker} value=${carId} onChange=${setCarId} />
    <div class="field">
      <label for="comment">Комментарий мастеру</label>
      <textarea id="comment" rows="2" maxlength="500" placeholder="Необязательно. Например: приеду на 5 минут раньше"
        value=${comment} onInput=${(e) => setComment(e.target.value)}></textarea>
    </div>
    <p class="hint">Баллами можно оплатить до ${CONFIG.maxDiscount}% чека — скажите мастеру при расчёте.</p>
    <div class="sticky-actions">
      <button class="btn btn-primary btn-lg" type="button" disabled=${busy} onClick=${() => confirm(comment, carId)}>
        ${busy ? "Записываем…" : "Записаться"}
      </button>
    </div>
  </section>`;
}

/** Запись создана: знак «получилось» загорается один раз, время крупно,
    код — ниже: «когда ехать» важнее, код понадобится только на посту. */
function Created({ booking, onDone }) {
  const point = booking.service_point;
  return html`<div class="stack-lg">
    <div class="done-head">
      <span class="done-mark" dangerouslySetInnerHTML=${{ __html: window.App.icon("check", 30) }}></span>
      <h2>Вы записаны</h2>
      <p class="done-when">${visitTime(booking.start_at, point.timezone)}</p>
    </div>
    <div class="ticket-stub ticket-stub-solo">
      <span class="muted">Код на посту</span>
      <b class="ticket-code">${booking.code}</b>
    </div>
    <div class="card pad info-list">
      <${InfoRow} icon="pin" label=${point.name}>${point.address}</${InfoRow}>
      <${InfoRow} icon=${kindIcon(booking.category_kind)} label=${booking.category_title || "Услуга"}>${booking.service_title}</${InfoRow}>
      ${booking.car && html`<${InfoRow} icon="car" label="Машина">${carLabel(booking.car)}</${InfoRow}>`}
    </div>
    ${booking.oil_on_site && html`<p class="hint">${CALLBACK_TEXT}.</p>`}
    <button class="btn btn-primary btn-block btn-lg" type="button" onClick=${onDone}>Готово</button>
  </div>`;
}
