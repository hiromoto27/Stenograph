# Стенограф

Локальный диктофон: речь → задачи → протоколы → напоминания → карта связей.

Репозиторий: https://github.com/hiromoto27/Stenograph

## Три способа пользоваться

### 1. Веб

Приложение уже работает в превью Grok (вкладка справа в чате).

Самим:

```bash
git clone https://github.com/hiromoto27/Stenograph.git
cd Stenograph
npm install
npm run dev
```

Откройте http://localhost:8080
Windows: Edge → «Установить как приложение».
Телефон: Chrome → «Добавить на главный экран».

### 2. Windows .exe

Нужны Rust (`rustup`) и WebView2.

```bash
npm i -D @tauri-apps/cli
npx tauri build --bundles nsis
```

Или GitHub Actions → **Release** → артефакт `*-setup.exe`.
Каркас: `src-tauri/`.

### 3. Android .apk

Нужны JDK 17 и Android SDK.

```bash
npx cap add android
npx cap sync android
cd android && ./gradlew assembleDebug
```

APK: `android/app/build/outputs/apk/debug/app-debug.apk`
Или workflow **Release**, job `apk`.

## Перенос данных веб → ПК / телефон

1. Веб → **Ещё** → **Выгрузить данные** → `stenograph-ГГГГ-ММ-ДД.json`
2. На ПК или Android → **Ещё** → **Загрузить данные** → этот файл

Переносятся задачи, реплики, протоколы, связи карты, напоминания и настройки.
