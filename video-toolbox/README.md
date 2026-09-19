# Video Toolbox — урок 1

Первая версия интерфейса личного видеоконвертера.

На этом этапе работает frontend:

- поле для ссылки;
- проверка корректности URL;
- демонстрация будущих режимов Video, Audio и Transcript;
- адаптивный интерфейс для компьютера и телефона.

Скачивание и расшифровка пока намеренно не подключены. На следующем этапе мы добавим backend на Python + FastAPI и первый API endpoint.

## Запуск

Установите Node.js LTS: https://nodejs.org/

Откройте терминал в папке `video-toolbox` и выполните:

```bash
npm run install:all
npm run dev
```

После запуска откройте адрес, показанный терминалом. Обычно это:

```text
http://localhost:5173
```

Остановить сайт можно сочетанием `Ctrl + C`.

## Структура

```text
video-toolbox/
├── frontend/          интерфейс сайта
│   ├── src/
│   │   ├── App.jsx    главный React-компонент
│   │   ├── main.jsx   точка запуска React
│   │   └── styles.css оформление
│   ├── index.html     HTML-страница
│   └── package.json   зависимости frontend
├── backend/           здесь появится FastAPI
├── package.json       общие команды проекта
└── README.md          инструкция
```

