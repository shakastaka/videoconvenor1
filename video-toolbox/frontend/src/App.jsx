import { useMemo, useState } from "react";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
const apiUrl = (path) => `${API_BASE}${path}`;

const outputModes = [
  { id: "video", label: "Video", hint: "MP4" },
  { id: "audio", label: "Audio", hint: "MP3" },
  { id: "transcript", label: "Transcript", hint: "TXT · SRT · VTT" },
];

const formatOptions = {
  audio: ["320 kbps", "192 kbps", "128 kbps"],
  transcript: ["TXT", "SRT", "VTT"],
};

const features = [
  { index: "01", title: "Видео", text: "Реальное скачивание в MP4 с выбором доступного разрешения.", tone: "violet" },
  { index: "02", title: "Аудио", text: "Извлечение звуковой дорожки в MP3 с битрейтом до 320 kbps.", tone: "cyan" },
  { index: "03", title: "Текст", text: "Локальная расшифровка речи с таймкодами в TXT, SRT или VTT.", tone: "lime" },
];

function parseUrl(value) {
  try {
    const parsed = new URL(value);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed : null;
  } catch {
    return null;
  }
}

function formatDuration(totalSeconds) {
  if (!Number.isFinite(totalSeconds) || totalSeconds < 0) return "—";
  const seconds = Math.floor(totalSeconds % 60).toString().padStart(2, "0");
  const minutes = Math.floor(totalSeconds / 60) % 60;
  const hours = Math.floor(totalSeconds / 3600);
  return hours ? `${hours}:${minutes.toString().padStart(2, "0")}:${seconds}` : `${minutes}:${seconds}`;
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
  const isOnline = !["localhost", "127.0.0.1"].includes(window.location.hostname);
  const [url, setUrl] = useState("");
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState("");
  const [source, setSource] = useState(null);
  const [mode, setMode] = useState("video");
  const [option, setOption] = useState("1080p");
  const [language, setLanguage] = useState("auto");
  const [notice, setNotice] = useState("");
  const [downloading, setDownloading] = useState(false);

  const qualities = useMemo(() => {
    if (!source?.qualities?.length) return ["720p"];
    return source.qualities.map((height) => `${height}p`);
  }, [source]);

  const activeOptions = mode === "video" ? qualities : formatOptions[mode];

  const downloadHref = useMemo(() => {
    if (!source) return "#";
    const encodedUrl = encodeURIComponent(source.webpage_url);
    if (mode === "video") {
      return apiUrl(`/api/download/video?url=${encodedUrl}&quality=${option.replace("p", "")}`);
    } else if (mode === "audio") {
      return apiUrl(`/api/download/audio?url=${encodedUrl}&bitrate=${option.replace(" kbps", "")}`);
    } else {
      return apiUrl(`/api/transcribe?url=${encodedUrl}&language=${language}&output_format=${option.toLowerCase()}`);
    }
  }, [source, mode, option, language]);

  function handleModeChange(nextMode) {
    setMode(nextMode);
    setOption(nextMode === "video" ? qualities[0] : formatOptions[nextMode][0]);
    setNotice("");
  }

  async function handleAnalyze(event) {
    event.preventDefault();
    const parsed = parseUrl(url.trim());

    if (!parsed) {
      setError("Нужна полная ссылка, начинающаяся с http:// или https://");
      return;
    }

    setError("");
    setNotice("");
    setStatus("loading");

    try {
      const response = await fetch(apiUrl("/api/analyze"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: parsed.href }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const hostedWithoutBackend = response.status === 404 && window.location.hostname.endsWith("chatgpt.site");
        throw new Error(hostedWithoutBackend
          ? "Интерфейс опубликован, но онлайн-backend ещё не подключён. Полная версия работает через start_windows.bat."
          : payload.detail || "Источник не удалось обработать");
      }

      setSource(payload);
      setOption(`${payload.qualities?.[0] || 720}p`);
      setStatus("ready");
    } catch (requestError) {
      setStatus("idle");
      setError(requestError.message === "Failed to fetch"
        ? "Backend не запущен. Откройте проект через start_windows.bat"
        : requestError.message);
    }
  }

  function startDownload() {
    setDownloading(true);
    if (mode === "video") {
      setNotice("MP4 готовится. Большое видео может занять несколько минут — не закрывайте окно терминала и текущую вкладку.");
    } else if (mode === "audio") {
      setNotice("MP3 извлекается из клипа. Обработка может занять время в зависимости от размера видео — не закрывайте вкладку.");
    } else {
      setNotice("Распознаём речь локально. При первом запуске модель загрузится автоматически, поэтому потребуется больше времени. Не закрывайте текущую вкладку.");
    }
    window.setTimeout(() => setDownloading(false), 6000);
  }

  function resetResult() {
    setStatus("idle");
    setSource(null);
    setUrl("");
    setMode("video");
    setOption("1080p");
    setLanguage("auto");
    setNotice("");
    setDownloading(false);
  }

  return (
    <div className="site-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Video Toolbox — наверх">
          <span className="brand-symbol"><span /></span>
          <span className="brand-copy"><strong>Video Toolbox</strong><small>Media utility</small></span>
        </a>
        <div className="topbar-meta">
          <span className="status-pill"><i /> {isOnline ? "ONLINE" : "LOCAL MODE"}</span>
          <span className="version">V1.2</span>
        </div>
      </header>

      <main id="top">
        <section className={`hero ${status === "ready" ? "hero-compact" : ""}`}>
          <div className="hero-kicker"><span>ONE PUBLIC LINK</span><i />THREE OUTPUTS</div>
          <h1>Забери из видео<br /><em>именно то, что нужно.</em></h1>
          <p className="hero-text">Video Toolbox сохраняет публичное видео в MP4, извлекает MP3 и создаёт расшифровку с таймкодами. Для TikTok выбирается чистый исходный поток, когда он доступен.</p>

          <form className="analyze-form" onSubmit={handleAnalyze} noValidate>
            <label htmlFor="video-url">Ссылка на видео</label>
            <div className={`input-shell ${error ? "has-error" : ""}`}>
              <span className="input-icon"><AppIcon name="link" /></span>
              <input id="video-url" value={url} onChange={(event) => { setUrl(event.target.value); setError(""); }} placeholder="https://youtube.com/watch?v=..." autoComplete="off" disabled={status === "loading"} />
              <button className="analyze-button" type="submit" disabled={status === "loading"}>
                {status === "loading" ? "Анализируем" : "Обработать"}
                {status === "loading" ? <span className="spinner" /> : <AppIcon name="arrow" />}
              </button>
            </div>
            <div className="form-meta">
              <span>Публичные источники, поддерживаемые yt-dlp · без DRM</span>
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

        {status === "ready" && source && (
          <section className="result-section" aria-live="polite">
            <div className="section-heading">
              <div><span className="section-label">РЕЗУЛЬТАТ АНАЛИЗА</span><h2>Выберите, что получить</h2></div>
              <button className="reset-button" type="button" onClick={resetResult}><AppIcon name="refresh" />Новая ссылка</button>
            </div>

            <div className="result-card">
              <div className={`preview-panel ${source.thumbnail ? "has-thumbnail" : ""}`} style={source.thumbnail ? { backgroundImage: `linear-gradient(rgba(8,8,10,.16),rgba(8,8,10,.5)),url(${source.thumbnail})` } : undefined}>
                {!source.thumbnail && <div className="preview-grid" />}
                <span className="provider-chip">{source.extractor || "Источник"}</span>
                <span className="play-button" aria-hidden="true"><AppIcon name="play" /></span>
                <span className="duration">{formatDuration(source.duration)}</span>
                <div className="preview-caption"><span>ИСТОЧНИК НАЙДЕН</span><strong>{source.title}</strong></div>
              </div>

              <div className="output-panel">
                <div className="source-info">
                  <div><span className="demo-badge">BACKEND CONNECTED</span><h3>{source.title}</h3><p title={source.webpage_url}>{source.uploader || source.extractor || "Публичный источник"}</p></div>
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
                    <span>{mode === "video" ? "Качество видео" : mode === "audio" ? "Качество MP3" : "Формат текста"}</span>
                    <small>{mode === "transcript" ? "с таймкодами" : "доступные варианты"}</small>
                  </div>
                  <div className="option-row">
                    {activeOptions.map((item) => (
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
                      <option value="auto">Автоопределение</option>
                      <option value="ru">Русский</option>
                      <option value="en">English</option>
                      <option value="sl">Slovenščina</option>
                    </select>
                  </div>
                )}

                <div className="source-policy">
                  <AppIcon name="shield" />
                  <p><strong>{mode === "transcript" ? "Локальное распознавание" : "Без искусственного удаления знаков"}</strong><span>{mode === "transcript" ? "Аудио обрабатывается на вашем компьютере и удаляется после выдачи файла." : "Берём чистый исходный поток, когда он доступен. Вшитый водяной знак не стирается и не обрезается."}</span></p>
                </div>

                <a className="primary-action" href={downloadHref} download onClick={(e) => { if (downloading) e.preventDefault(); else startDownload(); }} aria-disabled={downloading}>
                  {downloading ? "Обрабатываем" : mode === "video" ? "Скачать MP4" : mode === "audio" ? "Скачать MP3" : "Создать расшифровку"}<span>{option}</span>{downloading ? <span className="spinner dark" /> : <AppIcon name="arrow" />}
                </a>
                {notice && <div className="backend-notice">{notice}</div>}
              </div>
            </div>
          </section>
        )}

        <section className="feature-section">
          <div className="section-heading features-heading">
            <div><span className="section-label">ВОЗМОЖНОСТИ</span><h2>Одна ссылка. Три инструмента.</h2></div>
            <p>Видео и звук обрабатывает FFmpeg, а расшифровка создаётся локальной моделью Whisper без оплаты за каждую минуту.</p>
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
          <div><strong>Используйте только свои или разрешённые материалы</strong><p>Приватные, платные и DRM-защищённые видео намеренно не поддерживаются.</p></div>
          <span className="privacy-status"><i /> LOCAL FIRST</span>
        </section>
      </main>

      <footer>
        <div className="footer-brand"><span className="brand-symbol small"><span /></span>Video Toolbox</div>
        <span>Final v1.2 · React + FastAPI</span>
        <span>MP4 · MP3 · TXT/SRT/VTT</span>
      </footer>
    </div>
  );
}

