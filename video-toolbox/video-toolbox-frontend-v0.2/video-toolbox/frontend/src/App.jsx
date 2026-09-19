import { useMemo, useState } from "react";

const outputModes = [
  { id: "video", label: "Video", hint: "MP4" },
  { id: "audio", label: "Audio", hint: "MP3" },
  { id: "transcript", label: "Transcript", hint: "TXT · SRT · VTT" },
];

const formatOptions = {
  video: ["1080p", "720p", "480p"],
  audio: ["320 kbps", "192 kbps", "128 kbps"],
  transcript: ["TXT", "SRT", "VTT"],
};

const features = [
  { index: "01", title: "Видео", text: "Исходное качество, MP4 и выбор доступного разрешения.", tone: "violet" },
  { index: "02", title: "Аудио", text: "Чистая звуковая дорожка в MP3 — без лишних действий.", tone: "cyan" },
  { index: "03", title: "Текст", text: "Расшифровка речи с таймкодами в TXT, SRT или VTT.", tone: "lime" },
];

function parseUrl(value) {
  try {
    const parsed = new URL(value);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed : null;
  } catch {
    return null;
  }
}

function getProvider(hostname) {
  const host = hostname.replace("www.", "").toLowerCase();
  if (host.includes("youtu")) return "YouTube";
  if (host.includes("tiktok")) return "TikTok";
  if (host.includes("instagram")) return "Instagram";
  if (host.includes("vimeo")) return "Vimeo";
  if (host.includes("twitter") || host.includes("x.com")) return "X / Twitter";
  return host;
}

function formatAction(mode) {
  if (mode === "video") return "Подготовить видео";
  if (mode === "audio") return "Подготовить MP3";
  return "Создать расшифровку";
}

function AppIcon({ name }) {
  const icons = {
    link: <path d="M10.6 13.4a4.4 4.4 0 0 0 6.2.1l2.7-2.7a4.4 4.4 0 0 0-6.2-6.2l-1.6 1.6M13.4 10.6a4.4 4.4 0 0 0-6.2-.1l-2.7 2.7a4.4 4.4 0 0 0 6.2 6.2l1.6-1.6" />,
    shield: <path d="M12 3 5 6v5c0 4.6 2.9 8.5 7 10 4.1-1.5 7-5.4 7-10V6l-7-3Zm-3 9 2 2 4-4" />,
    arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
    refresh: <path d="M20 7v5h-5M4 17v-5h5m9.5-3A7 7 0 0 0 6.2 6.2L4 8m16 8-2.2 1.8A7 7 0 0 1 5.5 15" />,
    play: <path d="m9 7 8 5-8 5V7Z" />,
    check: <path d="m5 12 4 4L19 6" />,
  };

  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {icons[name]}
    </svg>
  );
}

export default function App() {
  const [url, setUrl] = useState("");
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");
  const [source, setSource] = useState(null);
  const [mode, setMode] = useState("video");
  const [option, setOption] = useState("1080p");
  const [language, setLanguage] = useState("Автоопределение");
  const [notice, setNotice] = useState("");

  const hostname = useMemo(() => source?.hostname?.replace("www.", "") ?? "", [source]);
  const provider = source ? getProvider(source.hostname) : "";

  function handleModeChange(nextMode) {
    setMode(nextMode);
    setOption(formatOptions[nextMode][0]);
    setNotice("");
  }

  function handleAnalyze(event) {
    event.preventDefault();
    const parsed = parseUrl(url.trim());

    if (!parsed) {
      setError("Нужна полная ссылка, начинающаяся с http:// или https://");
      setStatus("idle");
      return;
    }

    setError("");
    setNotice("");
    setStatus("loading");
    window.setTimeout(() => {
      setSource(parsed);
      setStatus("ready");
    }, 950);
  }

  function resetResult() {
    setStatus("idle");
    setSource(null);
    setUrl("");
    setMode("video");
    setOption("1080p");
    setNotice("");
  }

  return (
    <div className="site-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Video Toolbox — наверх">
          <span className="brand-symbol"><span /></span>
          <span className="brand-copy"><strong>Video Toolbox</strong><small>Media utility</small></span>
        </a>
        <div className="topbar-meta">
          <span className="status-pill"><i /> LOCAL MODE</span>
          <span className="version">V0.2 FRONTEND</span>
        </div>
      </header>

      <main id="top">
        <section className={`hero ${status === "ready" ? "hero-compact" : ""}`}>
          <div className="hero-kicker"><span>ONE LINK</span><i />THREE OUTPUTS</div>
          <h1>Забери из видео<br /><em>именно то, что нужно.</em></h1>
          <p className="hero-text">Вставь публичную ссылку. Video Toolbox определит источник и подготовит видео, аудиодорожку или расшифровку.</p>

          <form className="analyze-form" onSubmit={handleAnalyze} noValidate>
            <label htmlFor="video-url">Ссылка на видео</label>
            <div className={`input-shell ${error ? "has-error" : ""}`}>
              <span className="input-icon"><AppIcon name="link" /></span>
              <input
                id="video-url"
                value={url}
                onChange={(event) => { setUrl(event.target.value); setError(""); }}
                placeholder="https://youtube.com/watch?v=..."
                autoComplete="off"
                disabled={status === "loading"}
              />
              <button className="analyze-button" type="submit" disabled={status === "loading"}>
                {status === "loading" ? "Анализируем" : "Обработать"}
                {status === "loading" ? <span className="spinner" /> : <AppIcon name="arrow" />}
              </button>
            </div>
            <div className="form-meta">
              <span>YouTube · TikTok · Instagram · Vimeo · другие источники</span>
              {error && <strong>{error}</strong>}
            </div>
          </form>

          {status === "loading" && (
            <div className="loading-panel" aria-live="polite">
              <div className="loading-topline"><span>Проверяем источник и доступные форматы</span><span>01 / 03</span></div>
              <div className="progress-track"><span /></div>
              <div className="loading-steps"><span className="active"><i />Ссылка принята</span><span><i />Метаданные</span><span><i />Форматы</span></div>
            </div>
          )}
        </section>

        {status === "ready" && (
          <section className="result-section" aria-live="polite">
            <div className="section-heading">
              <div><span className="section-label">РЕЗУЛЬТАТ АНАЛИЗА</span><h2>Выбери, что получить</h2></div>
              <button className="reset-button" type="button" onClick={resetResult}><AppIcon name="refresh" />Новая ссылка</button>
            </div>

            <div className="result-card">
              <div className="preview-panel">
                <div className="preview-grid" />
                <span className="provider-chip">{provider}</span>
                <button className="play-button" type="button" aria-label="Предпросмотр недоступен"><AppIcon name="play" /></button>
                <span className="duration">03:42</span>
                <div className="preview-caption"><span>PREVIEW</span><strong>Будет загружено backend-сервисом</strong></div>
              </div>

              <div className="output-panel">
                <div className="source-info">
                  <div><span className="demo-badge">FRONTEND DEMO</span><h3>Видео готово к обработке</h3><p title={source.href}>{hostname}</p></div>
                  <span className="source-check"><AppIcon name="check" /></span>
                </div>

                <div className="mode-tabs" role="tablist" aria-label="Тип результата">
                  {outputModes.map((item) => (
                    <button key={item.id} type="button" className={mode === item.id ? "active" : ""} onClick={() => handleModeChange(item.id)} role="tab" aria-selected={mode === item.id}>
                      <strong>{item.label}</strong><small>{item.hint}</small>
                    </button>
                  ))}
                </div>

                <div className="settings-block">
                  <div className="settings-label">
                    <span>{mode === "video" ? "Качество видео" : mode === "audio" ? "Качество аудио" : "Формат текста"}</span>
                    <small>{mode === "transcript" ? "с таймкодами" : "доступные варианты"}</small>
                  </div>
                  <div className="option-row">
                    {formatOptions[mode].map((item) => (
                      <button key={item} type="button" className={option === item ? "selected" : ""} onClick={() => setOption(item)}>
                        {option === item && <AppIcon name="check" />}{item}
                      </button>
                    ))}
                  </div>
                </div>

                {mode === "transcript" && (
                  <div className="language-row">
                    <label htmlFor="language">Язык речи</label>
                    <select id="language" value={language} onChange={(event) => setLanguage(event.target.value)}>
                      <option>Автоопределение</option><option>Русский</option><option>English</option><option>Slovenščina</option>
                    </select>
                  </div>
                )}

                <button className="primary-action" type="button" onClick={() => setNotice("Интерфейс готов. Реальную обработку подключим через FastAPI на следующем этапе.")}>
                  {formatAction(mode)}<span>{option}</span><AppIcon name="arrow" />
                </button>
                {notice && <div className="backend-notice">{notice}</div>}
              </div>
            </div>
          </section>
        )}

        <section className="feature-section">
          <div className="section-heading features-heading">
            <div><span className="section-label">ВОЗМОЖНОСТИ</span><h2>Одна ссылка. Три инструмента.</h2></div>
            <p>Никаких лишних экранов — только источник, формат и готовый результат.</p>
          </div>
          <div className="feature-grid">
            {features.map((feature) => (
              <article className={`feature-card ${feature.tone}`} key={feature.index}>
                <span className="feature-index">{feature.index}</span><div className="feature-symbol"><span /></div><h3>{feature.title}</h3><p>{feature.text}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="privacy-strip">
          <span className="privacy-icon"><AppIcon name="shield" /></span>
          <div><strong>Приватность по умолчанию</strong><p>История не сохраняется. Временные файлы будут автоматически удаляться после обработки.</p></div>
          <span className="privacy-status"><i /> LOCAL FIRST</span>
        </section>
      </main>

      <footer>
        <div className="footer-brand"><span className="brand-symbol small"><span /></span>Video Toolbox</div>
        <span>Frontend v0.2 · React + Vite</span>
        <span>Следующий этап: FastAPI</span>
      </footer>
    </div>
  );
}
