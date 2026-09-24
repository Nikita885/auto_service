/* Кто и как попадает в веб-приложение.

   Веб-приложение — только для iPhone и только установленное на главный
   экран. Android получает настоящее приложение из Google Play, компьютер —
   QR-код, чтобы открыть страницу на телефоне. В Safari на iPhone вместо
   входа — инструкция «На экран „Домой“»: из браузера приложением не
   пользуются, потому что у него своё хранилище и вход из Safari туда не
   переедет, а уведомления приходят только установленному.

   Код приглашения при этом не теряется: он уже лежит в start_url
   манифеста (см. ClientAppView), и установленное приложение откроется с
   ним. */

import { CONFIG, html, isIos, isStandalone } from "app/lib";

/** Что показать вместо приложения, или null — можно работать. */
export function gate() {
  if (!isIos()) return "not-iphone";
  if (!isStandalone() && !CONFIG.allowBrowser) return "install";
  return null;
}

function ShareIcon() {
  return html`<svg class="share-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
    stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <path d="M12 3v12M8 7l4-4 4 4"/><path d="M6 11H5a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-8a1 1 0 0 0-1-1h-1"/>
  </svg>`;
}

function Brand() {
  return html`<div class="auth-brand"><img src=${CONFIG.icon} alt="" /><b>${CONFIG.company}</b></div>`;
}

/** iPhone, Safari: только инструкция, входа нет. */
export function InstallGate() {
  return html`<main class="screen screen-plain">
    <div class="auth gate">
      <${Brand} />
      <div>
        <h1>Установите приложение<br /><span>на главный экран</span></h1>
        <p class="muted" style="margin-top:8px">Приложение работает только с главного экрана iPhone —
          так приходят уведомления, а вход сохраняется. Это три касания.</p>
      </div>
      <ol class="install-steps card pad">
        <li><span class="step-n">1</span><span>Нажмите «Поделиться» <${ShareIcon} /> внизу экрана Safari</span></li>
        <li><span class="step-n">2</span><span>Прокрутите и выберите <b>«На экран „Домой“»</b></span></li>
        <li><span class="step-n">3</span><span>Нажмите <b>«Добавить»</b> и откройте приложение с иконкой</span></li>
      </ol>
      <p class="hint center">Открыто не в Safari? Скопируйте адрес страницы и откройте его в Safari —
        другие браузеры на iPhone не умеют ставить приложения на главный экран.</p>
      <div class="install-arrow gate-arrow" aria-hidden="true">↓</div>
    </div>
  </main>`;
}

function Qr({ text }) {
  if (!window.qrcode) return null;
  const qr = window.qrcode(0, "M");
  qr.addData(text);
  qr.make();
  // SVG строит библиотека из нашего же адреса — чужих данных в нём нет.
  return html`<div class="qr" role="img" aria-label="QR-код для iPhone"
    dangerouslySetInnerHTML=${{ __html: qr.createSvgTag({ cellSize: 4, margin: 0, scalable: true }) }}></div>`;
}

/** Android и компьютер: веб-приложение не для них. */
export function NotIphoneGate() {
  const android = /android/i.test(navigator.userAgent);
  const appUrl = CONFIG.siteUrl + "/app/" + location.search;
  return html`<main class="screen screen-plain">
    <div class="auth gate">
      <${Brand} />
      ${android ? html`
        <div>
          <h1>Для Android —<br /><span>приложение из Google Play</span></h1>
          <p class="muted" style="margin-top:8px">Это веб-приложение сделано для iPhone. На Android
            запись, бонусы и уведомления — в нашем приложении.</p>
        </div>
        ${CONFIG.playUrl
          ? html`<a class="btn btn-primary btn-block" href=${CONFIG.playUrl}>Открыть в Google Play</a>`
          : html`<p class="card pad muted">Приложение скоро появится в Google Play. Пока записывайтесь
              по телефону <a href=${"tel:" + CONFIG.phone.replace(/[^\d+]/g, "")}>${CONFIG.phone}</a>.</p>`}
      ` : html`
        <div>
          <h1>Откройте<br /><span>на iPhone</span></h1>
          <p class="muted" style="margin-top:8px">Веб-приложение ставится на главный экран iPhone.
            Наведите камеру телефона на код — страница откроется в Safari.</p>
        </div>
        <div class="card pad center"><${Qr} text=${appUrl} /></div>
        <p class="hint center">На Android — приложение из Google Play, ссылка на главной странице сайта.</p>
      `}
    </div>
  </main>`;
}
