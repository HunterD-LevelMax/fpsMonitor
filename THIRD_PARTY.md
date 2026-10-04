# Сторонние компоненты

Приложение само по себе написано на Python и не требует ничего, кроме стандартной
библиотеки. Для чтения FPS и датчиков подключаются готовые инструменты — они не входят в
репозиторий и скачиваются скриптами из `tools/`.

| Компонент | Версия | Лицензия | Что делает | Как получить |
|---|---|---|---|---|
| [PresentMon](https://github.com/GameTechDev/PresentMon) (Intel) | 2.6.0 | MIT | FPS и время кадра через провайдер ETW `Microsoft-Windows-DxgKrnl` | `python tools\fetch_vendor.py` |
| [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) | 0.9.6 | MPL-2.0 | температура, мощность и частоты CPU (драйвер Ring0 / PawnIO) | `python tools\fetch_vendor.py` |
| [psutil](https://github.com/giampaolo/psutil) | 7.2.2 | BSD-3-Clause | загрузка CPU и память | `python tools\fetch_psutil.py` |
| [PawnIO](https://pawnio.eu/) | 2.1.0 | — | подписанный драйвер доступа к датчикам CPU; нужен там, где Windows блокирует WinRing0 | встроен в `LibreHardwareMonitor.exe`; ставится кнопкой на вкладке «Диагностика» |

Скачанные файлы попадают в `vendor/` и `libs/`, которые исключены из репозитория
(`.gitignore`), потому что это чужие бинарники, а не исходный код проекта.

Приложение только запускает эти инструменты и читает их вывод, поэтому лицензии на сам код
проекта они не затрагивают. При распространении собранной версии (архив из Releases) укажите
эти компоненты так же, как указано здесь.

## Приватность изменений

`app/sources/pawnio.py` умеет распаковать встроенный в LibreHardwareMonitor установщик
PawnIO и запустить его с ключом `-install -silent`. Это установка kernel-драйвера, поэтому
она выполняется **только по нажатию кнопки пользователем** и никогда автоматически.
