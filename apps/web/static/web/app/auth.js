/* Вход по номеру и знакомство — одни экраны для iPhone и Android.

   Редизайн (октябрь 2026, «короткий вход сверху»): блок прижат к верху
   экрана — клавиатура не закрывает кнопку (Grab, Any Distance на
   Mobbin). Код — четыре ячейки и отправка сама, как только введена
   последняя цифра; «позвоним ещё раз через 0:42» — строкой под ячейками
   (Abode), запасные пути — одной ссылкой «Не приходит звонок?» и окном
   снизу. Знакомство — два коротких шага: имя, потом машина. */

import {
  CONFIG, Sheet, api, call, canPaste, errorText, formatPhone, html, invite, pasteText, phoneComplete,
  toast, useEffect, useRef, useState,
} from "app/lib";
import { canScan, inviteFromText, scanInvite } from "app/scan";

/** Итог кода приглашения, пришедшего вместе со входом. */
export function reportInvite(result) {
  if (!result) return;
  invite.done();
  if (result.status === "attached") {
    toast("Вы в команде: " + result.inviter_name + ". Ваши замены будут приносить баллы пригласившему.", "ok", "Приглашение принято");
  } else if (result.code !== "referral_already_attached") {
    toast(result.message || "Код приглашения не подошёл.", "error");
  }
}

const CODE_LEN = 4;
const clock = (s) => Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");

function Brand() {
  return html`<div class="auth-brand"><img src=${CONFIG.icon} alt="" /><b>${CONFIG.company}</b></div>`;
}

export function Auth({ onSignedIn }) {
  const [step, setStep] = useState("phone");
  const [phone, setPhone] = useState("+7");
  const [code, setCode] = useState("");
  const [hint, setHint] = useState("");
  const [busy, setBusy] = useState(""); // "", "send" или "verify"
  const [resendIn, setResendIn] = useState(0);
  // Как пришёл код: call — звонок, код — последние 4 цифры входящего
  // номера; sms — после двух неудачных звонков сервер разрешает SMS.
  const [channel, setChannel] = useState("call");
  const [smsAvailable, setSmsAvailable] = useState(false);
  // Обратный звонок (OTP_MODE=verificahub): клиент сам звонит на этот
  // номер, а мы спрашиваем сервер, дошёл ли звонок. `session` — секрет,
  // без которого сервер статус не отдаст.
  const [numberToCall, setNumberToCall] = useState("");
  const [session, setSession] = useState("");
  const [callEnded, setCallEnded] = useState("");
  const [pending, setPending] = useState(invite.get());
  const [sheet, setSheet] = useState(null); // invite | help
  const codeRef = useRef(null);

  function remember(found) {
    invite.set(found);
    setPending(found);
    setSheet(null);
    toast("Код " + found + " сохранён — применится при входе.", "ok");
  }

  async function scan() {
    const found = await scanInvite();
    if (found) remember(found);
  }

  // iPhone: веб-приложение с главного экрана ссылку из Safari не получает —
  // человек копирует код (или всё сообщение со ссылкой) и вставляет одним
  // нажатием. Разбор тот же, что у сканера.
  async function paste() {
    const found = inviteFromText(await pasteText());
    if (!found) { toast("В буфере нет кода приглашения — скопируйте его из ссылки.", "error"); return; }
    remember(found);
  }

  useEffect(() => {
    if (resendIn <= 0) return undefined;
    const t = setTimeout(() => setResendIn((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [resendIn]);

  useEffect(() => { if (step === "code" && codeRef.current) codeRef.current.focus(); }, [step]);

  async function requestCode(wanted) {
    if (!phoneComplete(phone) || busy) return;
    setBusy("send");
    setSheet(null);
    const data = await call(() => api.request("/auth/otp/request/", {
      method: "POST", body: wanted ? { phone, channel: wanted } : { phone }, auth: false,
    }));
    setBusy("");
    if (!data) return;
    setStep("code");
    setCode("");
    setChannel(data.channel || "sms");
    setSmsAvailable(Boolean(data.sms_available));
    setNumberToCall(data.number_to_call || "");
    setSession(data.session || "");
    setCallEnded("");
    setResendIn(data.resend_after_seconds || 60);
    // Код в ответе приходит только номерам из OTP_DEBUG_PHONES — это
    // временная замена SMS, пока шлюз не заработал.
    if (data.debug_code) {
      setCode(data.debug_code);
      setHint("Тестовый номер: код пришёл в ответе сервера и уже подставлен.");
    } else {
      setHint("");
    }
  }

  function signedIn(data) {
    if (data.user.role !== "client") {
      toast("Этот номер принадлежит сотруднику. Рабочее место мастера — на сайте, в разделе /master/.", "error");
      return;
    }
    api.store.save(data.access, data.refresh);
    reportInvite(data.invite);
    onSignedIn(data.user, data.is_new_user);
  }

  /* Обратный звонок: раз в 2 секунды спрашиваем, дошёл ли звонок, и сразу
     — когда приложение вернулось на экран из «Телефона». Сбой шлюза не
     останавливает ожидание: следующий опрос спросит снова. */
  useEffect(() => {
    if (step !== "code" || channel !== "reverse_call" || !session || callEnded) return undefined;
    let stopped = false;
    let inFlight = false;

    async function poll() {
      if (stopped || inFlight) return;
      inFlight = true;
      try {
        const data = await api.request("/auth/otp/call-status/", {
          method: "POST", body: { phone, session, invite: invite.get() }, auth: false,
        });
        if (!stopped && data && data.access) { stopped = true; signedIn(data); }
      } catch (err) {
        if (err.code !== "otp_unavailable" && !stopped) {
          stopped = true;
          setCallEnded(errorText(err));
        }
      } finally {
        inFlight = false;
      }
    }

    const timer = setInterval(poll, 2000);
    const onVisible = () => { if (!document.hidden) poll(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stopped = true;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [step, channel, session, callEnded]);

  async function verify(value) {
    const entered = (value || code).trim();
    if (entered.length < CODE_LEN || busy) return;
    setBusy("verify");
    try {
      // Код приглашения из ссылки или QR уходит вместе со входом — сервер
      // привяжет человека сам, вводить ничего не придётся.
      const data = await api.request("/auth/otp/verify/", {
        method: "POST", body: { phone, code: entered, invite: invite.get() }, auth: false,
      });
      signedIn(data);
    } catch (err) {
      toast(errorText(err), "error");
      setCode("");
      if (codeRef.current) codeRef.current.focus();
    } finally {
      setBusy("");
    }
  }

  function onCode(e) {
    const digits = e.target.value.replace(/\D/g, "").slice(0, CODE_LEN);
    setCode(digits);
    // Последняя цифра — отправляем сами: лишнее касание на самом частом шаге.
    if (digits.length === CODE_LEN) verify(digits);
  }

  function changeNumber() {
    setStep("phone");
    setCode("");
    setSession("");
    setSheet(null);
  }

  const call_ = channel === "call";
  let content;
  if (step === "phone") {
    content = html`
      <div class="auth-copy">
        <h1>Вход по номеру</h1>
        <p class="muted">Пароль не нужен — подтвердим номер звонком.</p>
      </div>
      <form class="stack" onSubmit=${(e) => { e.preventDefault(); requestCode(null); }}>
        <div class="field">
          <label for="phone">Телефон</label>
          <input id="phone" class="phone-input" type="tel" inputmode="tel" autocomplete="tel" value=${phone}
            onInput=${(e) => setPhone(formatPhone(e.target.value))} />
        </div>
        <button class="btn btn-primary btn-block btn-lg" type="submit" disabled=${!phoneComplete(phone) || busy}>
          ${busy === "send" ? "Подождите…" : "Продолжить"}
        </button>
      </form>
      ${pending
        ? html`<p class="invite-note">Код приглашения <b>${pending}</b> применится при входе.</p>`
        : (canScan() || canPaste()) && html`<button class="link-btn auth-link" type="button"
            onClick=${() => setSheet("invite")}>У меня есть код приглашения</button>`}
    `;
  } else if (channel === "reverse_call") {
    content = html`
      <div class="auth-copy">
        <h1>Позвоните нам</h1>
        <p class="muted">С номера ${phone} позвоните на номер ниже — можно сбросить, как пойдут гудки.
          Звонок бесплатный, код вводить не нужно.</p>
      </div>
      <div class="stack">
        <a class="btn btn-primary btn-block btn-lg" href=${"tel:" + numberToCall}>
          Позвонить на ${formatPhone(numberToCall)}
        </a>
        ${callEnded
          ? html`<p class="hint hint-error">${callEnded}</p>`
          : html`<p class="hint call-wait" aria-live="polite"><span class="dot pulse"></span> Ждём ваш звонок…</p>`}
        ${hint && html`<p class="hint">${hint}</p>`}
        <button class="link-btn auth-link" type="button" onClick=${() => setSheet("help")}>Не получается позвонить?</button>
      </div>
    `;
  } else {
    content = html`
      <div class="auth-copy">
        <h1>${call_ ? "Последние 4 цифры" : "Код из SMS"}</h1>
        <p class="muted">${call_
          ? "Сейчас позвоним на " + phone + ". Отвечать не нужно — введите последние 4 цифры номера, с которого звонят."
          : "Отправили SMS на " + phone + "."}</p>
      </div>
      <form class="stack" onSubmit=${(e) => { e.preventDefault(); verify(); }}>
        <label class="code-cells" for="code">
          <span class="visually-hidden">${call_ ? "Последние 4 цифры входящего номера" : "Код из SMS"}</span>
          <input id="code" ref=${codeRef} inputmode="numeric" maxlength=${CODE_LEN} autocomplete="one-time-code"
            value=${code} onInput=${onCode} disabled=${busy === "verify"} />
          ${Array.from({ length: CODE_LEN }, (_, i) => html`<span key=${i}
            class=${"cell" + (i === Math.min(code.length, CODE_LEN - 1) && busy !== "verify" ? " is-current" : "")}
            aria-hidden="true">${code[i] || ""}</span>`)}
        </label>
        ${busy === "verify" && html`<p class="hint center">Проверяем…</p>`}
        ${code.length === CODE_LEN && !busy && html`<button class="btn btn-primary btn-block btn-lg" type="submit">Войти</button>`}
        ${hint && html`<p class="hint">${hint}</p>`}
        <p class="hint center">${resendIn > 0
          ? (call_ ? "Позвоним ещё раз через " : "Отправим ещё раз через ") + clock(resendIn)
          : html`<button class="link-btn" type="button" disabled=${busy}
              onClick=${() => requestCode(channel === "sms" && smsAvailable ? "sms" : null)}>
              ${call_ ? "Позвонить ещё раз" : "Отправить SMS ещё раз"}</button>`}</p>
        <button class="link-btn auth-link" type="button" onClick=${() => setSheet("help")}>
          ${call_ ? "Не приходит звонок?" : "Не приходит SMS?"}</button>
      </form>
    `;
  }

  return html`<main class="screen screen-plain">
    <div class="auth">
      <${Brand} />
      ${content}
      <p class="legal">Продолжая, вы соглашаетесь с обработкой персональных данных.</p>
    </div>
    ${sheet === "invite" && html`<${Sheet} title="Код приглашения" onClose=${() => setSheet(null)}>
      <div class="stack">
        <p class="muted">Скопируйте ссылку или код от друга и вставьте его здесь — или отсканируйте QR с его телефона.
          Код применится, как только вы войдёте.</p>
        ${canPaste() && html`<button class="btn btn-block btn-lg" type="button" onClick=${paste}>Вставить код</button>`}
        ${canScan() && html`<button class="btn btn-block btn-lg" type="button" onClick=${scan}>Сканировать QR</button>`}
      </div>
    </${Sheet}>`}
    ${sheet === "help" && html`<${Sheet} title=${channel === "reverse_call" ? "Не получается позвонить?" : "Не приходит код?"}
      onClose=${() => setSheet(null)}>
      <div class="list">
        ${smsAvailable && channel !== "sms" && html`<button class="list-row" type="button" disabled=${resendIn > 0 || busy}
          onClick=${() => requestCode("sms")}>
          <span class="list-body"><b>Прислать код в SMS</b>
            <span class="muted">${resendIn > 0 ? "Можно через " + clock(resendIn) : "Код придёт сообщением"}</span></span>
        </button>`}
        ${channel === "reverse_call" && html`<button class="list-row" type="button" disabled=${resendIn > 0 || busy}
          onClick=${() => requestCode(null)}>
          <span class="list-body"><b>Получить новый номер для звонка</b>
            <span class="muted">${resendIn > 0 ? "Можно через " + clock(resendIn) : "Если звонок не проходит"}</span></span>
        </button>`}
        <button class="list-row" type="button" onClick=${changeNumber}>
          <span class="list-body"><b>Изменить номер</b><span class="muted">${phone}</span></span>
        </button>
      </div>
      ${!smsAvailable && channel === "call" && html`<p class="hint">Если и второй звонок не придёт, предложим код в SMS.</p>`}
    </${Sheet}>`}
  </main>`;
}

/* ------------------------------------------------------------ машина */

/** Поле «марка и модель» с подсказками из справочника.

    Подсказка, а не ограничение: свою машину можно вписать как есть —
    справочник полным не бывает, и упираться в него на регистрации значит
    терять клиента. */
export function CarField({ value, onChange, id }) {
  const inputId = id || "car";
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const timer = useRef(null);

  function onInput(e) {
    const q = e.target.value;
    onChange(q);
    clearTimeout(timer.current);
    if (q.trim().length < 2) { setItems([]); return; }
    timer.current = setTimeout(async () => {
      try {
        const found = await api.get("/cars/search/?q=" + encodeURIComponent(q.trim()));
        setItems((found || []).slice(0, 6));
        setOpen(true);
      } catch (err) {
        setItems([]);
      }
    }, 250);
  }

  return html`<div class="field">
    <label for=${inputId}>Марка и модель</label>
    <input id=${inputId} autocomplete="off" placeholder="Например, Kia Rio" value=${value}
      onInput=${onInput} onBlur=${() => setTimeout(() => setOpen(false), 150)} />
    ${open && items.length > 0 && html`<div class="suggest" role="listbox">
      ${items.map((item) => html`<button type="button" key=${item.id} role="option"
        onMouseDown=${(e) => e.preventDefault()}
        onClick=${() => { onChange(item.title, item.id); setOpen(false); }}>${item.title}</button>`)}
    </div>`}
  </div>`;
}

/* ---------------------------------------------------------- знакомство */

/** Два коротких шага (Turo на Mobbin: один экран — одна вещь): имя, потом
    машина. Машина сохраняется прямо в гараж (`/garage/cars/`), а не в
    устаревшие поля профиля. Код приглашения из ссылки уже применён при
    входе — здесь его спрашиваем, только если кода не было. */
export function Onboarding({ user, onDone }) {
  const [step, setStep] = useState(user.full_name ? "car" : "name");
  const [name, setName] = useState(user.full_name || "");
  const [car, setCar] = useState("");
  const [modelId, setModelId] = useState(null);
  const [plate, setPlate] = useState("");
  const [code, setCode] = useState("");
  const [askCode, setAskCode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [me, setMe] = useState(user);

  async function saveName() {
    if (!name.trim()) { toast("Как к вам обращаться? Имя увидит мастер, когда вы приедете.", "error"); return; }
    setBusy(true);
    const saved = await call(() => api.patch("/auth/me/", { full_name: name.trim() }));
    setBusy(false);
    if (saved) { setMe(saved); setStep("car"); }
  }

  async function attachCode() {
    if (!code.trim()) return;
    try {
      await api.post("/referral/attach/", { code: code.trim() });
      toast("Приглашение принято", "ok");
    } catch (err) {
      if (err.code !== "referral_already_attached") toast("Код приглашения не подошёл: " + errorText(err), "error");
    }
    invite.done();
  }

  async function finish(skipCar) {
    setBusy(true);
    if (!skipCar && (car.trim() || plate.trim())) {
      const saved = await call(() => api.post("/garage/cars/", {
        title: car.trim(), plate: plate.trim(), model_id: modelId || null,
      }));
      if (!saved) { setBusy(false); return; }
    }
    await attachCode();
    setBusy(false);
    onDone(me);
  }

  async function scan() {
    const found = await scanInvite();
    if (found) { setCode(found); setAskCode(true); }
  }

  return html`<main class="screen screen-plain">
    <div class="auth">
      <div class="onboard-steps" aria-label=${"Шаг " + (step === "name" ? 1 : 2) + " из 2"}>
        <span class="is-done"></span><span class=${step === "car" ? "is-done" : ""}></span>
      </div>
      ${step === "name" ? html`
        <div class="auth-copy">
          <h1>Как вас зовут?</h1>
          <p class="muted">Имя увидит мастер, когда вы приедете.</p>
        </div>
        <form class="stack" onSubmit=${(e) => { e.preventDefault(); saveName(); }}>
          <div class="field">
            <label for="name">Имя</label>
            <input id="name" autocomplete="given-name" value=${name} onInput=${(e) => setName(e.target.value)} />
          </div>
          <button class="btn btn-primary btn-block btn-lg" type="submit" disabled=${busy || !name.trim()}>Дальше</button>
        </form>
      ` : html`
        <div class="auth-copy">
          <h1>Какая у вас машина?</h1>
          <p class="muted">Мастер будет знать, что заезжает, а гараж — подсказывать, когда менять масло.</p>
        </div>
        <form class="stack" onSubmit=${(e) => { e.preventDefault(); finish(false); }}>
          <${CarField} value=${car} onChange=${(value, id) => { setCar(value); setModelId(id || null); }} />
          <div class="field">
            <label for="plate">Госномер</label>
            <input id="plate" autocapitalize="characters" placeholder="Например, А123ВС174" value=${plate}
              onInput=${(e) => setPlate(e.target.value)} />
          </div>
          ${askCode && html`<div class="field">
            <label for="invite-code">Код приглашения</label>
            <input id="invite-code" class="code-field" autocapitalize="characters" value=${code}
              onInput=${(e) => setCode(e.target.value.toUpperCase())} />
          </div>`}
          <button class="btn btn-primary btn-block btn-lg" type="submit" disabled=${busy}>
            ${busy ? "Сохраняем…" : "Готово"}</button>
          <button class="btn btn-ghost btn-block" type="button" disabled=${busy} onClick=${() => finish(true)}>
            Добавлю машину позже</button>
          ${!askCode && !invite.get() && html`<div class="form-pair">
            <button class="link-btn" type="button" onClick=${() => setAskCode(true)}>Есть код приглашения</button>
            ${canScan() && html`<button class="link-btn" type="button" onClick=${scan}>Сканировать QR</button>`}
          </div>`}
        </form>
      `}
    </div>
  </main>`;
}
