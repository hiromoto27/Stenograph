# Дизайн Стенографа для Windows / Flet

Эталон — превью песочницы Grok (`src/styles.css`). ПК-версия должна выглядеть так же: палитра, тип, ритм. React не копировать.

## Характер

Тихий тёмный инструмент. Не админка, не фиолетовый Flet, не неон.

## Цвета

| Токен | Hex |
|---|---|
| bg | `#0B0C0E` |
| surface | `#141518` |
| surface-2 | `#1C1D21` |
| surface-3 | `#26272C` |
| fg | `#ECECE8` |
| muted | `#9A9B97` |
| subtle | `#6E6F6C` |
| border | `#2A2B2F` |
| primary | `#ECECE8` |
| primary-fg | `#0B0C0E` |
| rec | `#C45C4A` |
| rec-fg | `#FFF8F6` |
| ok | `#7D9A78` |
| warn | `#C4A574` |
| ring | `#C8C4BC` |

Запрещено: `#6750A4`, `#2563EB`, чистый `#FF0000`.

```python
page.bgcolor = "#0B0C0E"
page.theme_mode = ft.ThemeMode.DARK
page.theme = ft.Theme(
    color_scheme=ft.ColorScheme(
        primary="#ECECE8",
        on_primary="#0B0C0E",
        surface="#141518",
        on_surface="#ECECE8",
        outline="#2A2B2F",
        error="#C45C4A",
    )
)
```

Карточка: bgcolor `#141518`, border 1px `#2A2B2F`, radius 16.

## Шрифты

Витрина: Fraunces / Georgia / Constantia, 28–36, tracking чуть сжатый.
Текст: Source Sans 3 / Segoe UI, 14–16.
Моно: IBM Plex Mono.
Шрифты класть в assets/fonts, в exe без Google Fonts.

## Сетка

Контент ~1150 px. Desktop: справа задачи 300 px. Низ: 7 вкладок. Шапка: квадрат 36, поиск, точка записи. Кнопки 48 / 40. Радиусы 8, 12, 16, 24.

## Студия

Встреча → Слушать/Стоп/Непрерывно/Протокол → RMS → уточнение → лента.
Железо и путь модели только во вкладке Ещё.

## Кнопки

Главная: светлая. Запись: `#C45C4A`. Outline / ghost — тихие.
В шапке при записи: точка + «Идёт запись».

## Не делать

Тема Flet из коробки, DataTable на задачи, прогресс модели на студии, тяжёлые тени, светлую тему в v1.

## Приёмка

Рядом с превью Grok: те же hex, антиква в титуле, одна большая кнопка слушать, терракота записи. Иначе UI не готов.
