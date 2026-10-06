/* Вход по номеру и знакомство — те же шаги, что в приложении под Android. */

import {
  CONFIG, api, call, errorText, formatPhone, html, invite, phoneComplete, toast,
  useEffect, useRef, useState,
} from "app/lib";
import { canScan, scanInvite } from "app/scan";

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
  const codeRef = useRef(null);

  async function scan() {
    const code = await scanInvite();
    if (!code) return;
    invite.set(code);
    setPending(code);
    toast("Код " + code + " сохранён — применится при входе.", "ok");
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

  async function verify() {
    if (code.trim().length < 4 || busy) return;
    setBusy("verify");
    try {
      // Код приглашения из ссылки или QR уходит вместе со входом — сервер
      // привяжет человека сам, вводить ничего не придётся.
      const data = await api.request("/auth/otp/verify/", {
        method: "POST", body: { phone, code: code.trim(), invite: invite.get() }, auth: false,
      });
      signedIn(data);
    } catch (err) {
      toast(errorText(err), "error");
    } finally {
      setBusy("");
    }
  }

  return html`<main class="screen screen-plain">
    <div class="auth">
      <div class="auth-brand">
        <img src=${CONFIG.icon} alt="" />
        <b>${CONFIG.company}</b>
      </div>

      ${step === "phone" ? html`
        <div>
          <h1>Замена масла<br /><span>без очереди</span></h1>
          <p class="muted" style="margin-top:8px">Вход по номеру телефона, без пароля — подтвердим номер звонком.</p>
        </div>
        <form class="stack" onSubmit=${(e) => { e.preventDefault(); requestCode(null); }}>
          <div class="field">
            <label for="phone">Телефон</label>
            <input id="phone" type="tel" inputmode="tel" autocomplete="tel" value=${phone}
              onInput=${(e) => setPhone(formatPhone(e.target.value))} />
          </div>
          <button class="btn btn-primary btn-block" type="submit" disabled=${!phoneComplete(phone) || busy}>
            ${busy === "send" ? "Подождите…" : "Войти по номеру"}
          </button>
        </form>
        ${pending
          ? html`<p class="invite-note">Код приглашения <b>${pending}</b> применится автоматически при входе.</p>`
          : canScan() && html`<button class="btn btn-ghost btn-block" type="button" onClick=${scan}>
              Меня пригласили — сканировать QR-код</button>`}
      ` : channel === "reverse_call" ? html`
        <div>
          <h1>Позвоните нам</h1>
          <p class="muted" style="margin-top:8px">С номера ${phone} позвоните на номер ниже. Звонок бесплатный — можно сбросить сразу, как пойдут гудки. Код вводить не нужно: мы узнаем вас по номеру.</p>
        </div>
        <div class="stack">
          <a class="btn btn-primary btn-block btn-lg" href=${"tel:" + numberToCall}>
            Позвонить на ${formatPhone(numberToCall)}
          </a>
          ${callEnded
            ? html`<p class="hint hint-error">${callEnded}</p>`
            : html`<p class="hint call-wait" aria-live="polite"><span class="dot pulse"></span> Ждём ваш звонок…</p>`}
          ${hint && html`<p class="hint">${hint}</p>`}
          ${smsAvailable && html`
            <button class="btn btn-block" type="button" disabled=${resendIn > 0 || busy} onClick=${() => requestCode("sms")}>
              ${resendIn > 0 ? "Код в SMS — через " + resendIn + " с" : "Не получается позвонить — код в SMS"}
            </button>`}
          <button class="btn btn-ghost btn-block" type="button" disabled=${resendIn > 0 || busy}
            onClick=${() => requestCode(null)}>
            ${resendIn > 0 ? "Новый номер для звонка через " + resendIn + " с" : "Получить новый номер для звонка"}
          </button>
          <button class="btn btn-ghost btn-block" type="button" onClick=${() => { setStep("phone"); setSession(""); }}>
            Изменить номер
          </button>
        </div>
      ` : html`
        <div>
          <h1>Введите код</h1>
          <p class="muted" style="margin-top:8px">${channel === "call"
            ? "Сейчас на " + phone + " позвонят. Отвечать не нужно — введите последние 4 цифры номера, с которого звонят."
            : "Отправили SMS на " + phone}</p>
        </div>
        <form class="stack" onSubmit=${(e) => { e.preventDefault(); verify(); }}>
          <div class="field">
            <label for="code">${channel === "call" ? "Последние 4 цифры входящего номера" : "Код из SMS"}</label>
            <input id="code" ref=${codeRef} class="otp-input" inputmode="numeric" maxlength="8"
              autocomplete="one-time-code" value=${code}
              onInput=${(e) => setCode(e.target.value.replace(/\D/g, ""))} />
          </div>
          ${hint && html`<p class="hint">${hint}</p>`}
          <button class="btn btn-primary btn-block" type="submit" disabled=${code.length < 4 || busy}>
            ${busy === "verify" ? "Проверяем…" : "Войти"}
          </button>
          ${smsAvailable && channel === "call" && html`
            <button class="btn btn-block" type="button" disabled=${resendIn > 0 || busy} onClick=${() => requestCode("sms")}>
              ${resendIn > 0 ? "Код в SMS — через " + resendIn + " с" : "Звонок не приходит — получить код в SMS"}
            </button>`}
          <button class="btn btn-ghost btn-block" type="button" disabled=${resendIn > 0 || busy}
            onClick=${() => requestCode(channel === "sms" && smsAvailable ? "sms" : null)}>
            ${resendIn > 0
              ? (channel === "call" ? "Позвонить ещё раз через " : "Отправить SMS ещё раз через ") + resendIn + " с"
              : (channel === "call" ? "Позвонить ещё раз" : "Отправить SMS ещё раз")}
          </button>
          <button class="btn btn-ghost btn-block" type="button" onClick=${() => { setStep("phone"); setCode(""); }}>
            Изменить номер
          </button>
        </form>
      `}
      <p class="legal">Продолжая, вы соглашаетесь с обработкой персональных данных.</p>
    </div>
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
    ${open && items.length > 0 && html`<div class="suggest">
      ${items.map((item) => html`<button type="button" key=${item.id}
        onMouseDown=${(e) => e.preventDefault()}
        onClick=${() => { onChange(item.title, item.id); setOpen(false); }}>${item.title}</button>`)}
    </div>`}
  </div>`;
}

/* ---------------------------------------------------------- знакомство */

export function Onboarding({ user, onDone }) {
  const [name, setName] = useState(user.full_name || "");
  const [car, setCar] = useState(user.car_model || "");
  const [plate, setPlate] = useState(user.car_plate || "");
  const [code, setCode] = useState(invite.get());

  async function scan() {
    const found = await scanInvite();
    if (found) setCode(found);
  }
  const [busy, setBusy] = useState(false);

  async function save(skip) {
    if (!skip && !name.trim()) {
      toast("Без имени мастер не поймёт, кто приехал.", "error");
      return;
    }
    setBusy(true);
    let me = user;
    if (!skip) {
      me = await call(() => api.patch("/auth/me/", {
        full_name: name.trim(), car_model: car.trim(), car_plate: plate.trim().toUpperCase(),
      }));
      if (!me) { setBusy(false); return; }
    }
    if (code.trim()) {
      try {
        await api.post("/referral/attach/", { code: code.trim() });
        invite.done();
        toast("Приглашение принято", "ok");
      } catch (err) {
        invite.done();
        if (err.code !== "referral_already_attached") {
          toast("Код приглашения не подошёл: " + errorText(err) + " Профиль сохранён.", "error");
        }
      }
    }
    setBusy(false);
    onDone(me);
  }

  return html`<main class="screen screen-plain">
    <div class="screen-head">
      <h1>Давайте познакомимся</h1>
      <p>Имя и машину увидит мастер, когда вы приедете. Это займёт полминуты.</p>
    </div>
    <form class="card pad stack" onSubmit=${(e) => { e.preventDefault(); save(false); }}>
      <div class="field">
        <label for="name">Как вас зовут</label>
        <input id="name" autocomplete="name" value=${name} onInput=${(e) => setName(e.target.value)} />
      </div>
      <${CarField} value=${car} onChange=${setCar} />
      <div class="field">
        <label for="plate">Госномер</label>
        <input id="plate" autocapitalize="characters" placeholder="А123ВС174" value=${plate}
          onInput=${(e) => setPlate(e.target.value)} />
      </div>
      <div class="field">
        <label for="invite">Код приглашения, если есть</label>
        <div class="row" style="flex-wrap:nowrap">
          <input id="invite" style="flex:1" autocapitalize="characters" placeholder="Код приглашения" value=${code}
            onInput=${(e) => setCode(e.target.value.toUpperCase())} />
          ${canScan() && html`<button class="btn" type="button" onClick=${scan}>QR</button>`}
        </div>
        <span class="hint">Если вас пригласил знакомый — введите его код. Позже это можно сделать в «Бонусах».</span>
      </div>
      <button class="btn btn-primary btn-block" type="submit" disabled=${busy}>Готово</button>
      <button class="btn btn-ghost btn-block" type="button" disabled=${busy} onClick=${() => save(true)}>Заполнить позже</button>
    </form>
  </main>`;
}
