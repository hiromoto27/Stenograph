# Стенограф

## Почему `npm install` упал из `C:\\Users\\Hiro`

Npm ищет `package.json` **в текущей папке**.  
`C:\\Users\\Hiro` — это домашняя папка Windows, не проект.

```bat
cd %USERPROFILE%
git clone https://github.com/hiromoto27/Stenograph.git
cd Stenograph
npm install
```

Или сначала скачайте ZIP с GitHub → распакуйте → в проводнике откройте эту папку → в адресной строке наберите `cmd` → Enter → `npm install`.

Проверка, что вы в проекте:

```bat
cd
dir package.json
```

Должно показать файл `package.json`. Путь вроде `C:\\Users\\Hiro\\Stenograph`.

## Где живое приложение

Полный интерфейс сейчас работает в **превью Grok** (вкладка справа в этом чате).  
Репозиторий хранит исходники модулей (`src/lib`, карта, Whisper), а не готовый сборщик всего Vite-приложения.
