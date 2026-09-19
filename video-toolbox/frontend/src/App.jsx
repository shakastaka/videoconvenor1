import { useState } from "react";

const tools = [
  {
    number: "01",
    title: "Video",
    text: "Скачать исходное видео в доступном качестве.",
    accent: "violet",
  },
  {
    number: "02",
    title: "Audio",
    text: "Извлечь чистую аудиодорожку в формате MP3.",
    accent: "cyan",
  },
  {
    number: "03",
    title: "Transcript",
    text: "Получить текст, SRT или VTT с таймкодами.",
    accent: "lime",
  },
];

function isValidUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

export default function App() {
  const [url, setUrl] = useState("");
  const [message, setMessage] = useState("");

  function handleSubmit(event) {
    event.preventDefault();

    if (!isValidUrl(url.trim())) {
      setMessage("Вставь полную ссылку, начинающуюся с http:// или https://");
      return;
    }

    setMessage("Ссылка принята. На следующем этапе отправим её в backend через API.");
  }

  return (
    <main className="page-shell">
      <nav className="nav">
        <a className="brand" href="#top" aria-label="Video Toolbox — наверх">
          <span className="brand-mark">V</span>
          <span>Video Toolbox</span>
        </a>
        <span className="version">LOCAL · V0.1</span>
      </nav>

      <section className="hero" id="top">
        <div className="eyebrow"><span /> ONE LINK. THREE TOOLS.</div>
        <h1>
          Возьми видео.
          <br />
          <em>Оставь только нужное.</em>
        </h1>
        <p className="hero-copy">
          Вставь публичную ссылку на видео. Сервис определит источник и предложит
          доступные варианты обработки.
        </p>

        <form className="url-form" onSubmit={handleSubmit} noValidate>
          <label htmlFor="video-url">Ссылка на видео</label>
          <div className="input-row">
            <input
              id="video-url"
              value={url}
              onChange={(event) => {
                setUrl(event.target.value);
                setMessage("");
              }}
              placeholder="https://youtube.com/watch?v=..."
              autoComplete="off"
            />
            <button type="submit">
              Обработать
              <span aria-hidden="true">↗</span>
            </button>
          </div>
          <div className="form-footer">
            <span>YouTube · TikTok · Instagram · и другие источники</span>
            <span className={message.startsWith("Ссылка принята") ? "success" : "message"}>
              {message}
            </span>
          </div>
        </form>
      </section>

      <section className="tool-grid" aria-label="Возможности сервиса">
        {tools.map((tool) => (
          <article className={`tool-card ${tool.accent}`} key={tool.title}>
            <span className="tool-number">{tool.number}</span>
            <div>
              <h2>{tool.title}</h2>
              <p>{tool.text}</p>
            </div>
            <span className="tool-arrow" aria-hidden="true">↘</span>
          </article>
        ))}
      </section>

      <footer>
        <span>Работает локально на твоём компьютере</span>
        <span>Следующий этап: FastAPI backend</span>
      </footer>
    </main>
  );
}

