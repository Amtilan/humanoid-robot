# Агент видеостены — установка на ПК стены (Windows)

Агент — то же приложение `cortex-wall-agent`, что и имитатор в compose,
только с драйвером `sendinput`: он принимает команды робота по HTTP и
эмулирует клики/клавиши в приложении MinTrans (`Factories.exe`).

## Установка (Python-вариант)

1. Установить Python 3.12+ (галочка «Add to PATH»).
2. Скопировать на ПК папки `apps/wall-agent` и
   `packages/humanoid-robot-domain` (или установить wheel-файлы из релиза):

   ```powershell
   pip install .\humanoid_robot_domain-*.whl .\humanoid_robot_wall_agent-*.whl
   ```

3. Скопировать `mapping.example.json` → `C:\wall\mapping.json` и
   откалибровать координаты кликов под разрешение стены (пункт ниже).
4. Запуск:

   ```powershell
   cortex-wall-agent --driver sendinput --mapping C:\wall\mapping.json --token СЕКРЕТ --port 8093
   ```

5. Автозапуск как служба — через Планировщик заданий («При входе в
   систему», перезапуск при сбое) или NSSM:

   ```powershell
   nssm install WallAgent "C:\Python312\Scripts\cortex-wall-agent.exe" ^
       "--driver sendinput --mapping C:\wall\mapping.json --token СЕКРЕТ"
   ```

6. Брандмауэр: разрешить входящие на порт 8093 только из локальной сети
   робота.

На роботе указать адрес агента в `/etc/humanoid-robot/cortex-core.env`:

```
HR_WALL__AGENT_URL=http://<IP-ПК-стены>:8093
HR_WALL__TOKEN=СЕКРЕТ
```

## Калибровка mapping.json

Координаты клика — доли экрана (0..1): `[0.5, 0.5]` = центр. Порядок:

1. Открыть приложение стены в штатном (полноэкранном) режиме.
2. Для каждого раздела навести курсор на его кнопку, снять координаты
   (например, PowerShell: `Add-Type -AssemblyName System.Windows.Forms;
   [System.Windows.Forms.Cursor]::Position`), поделить на ширину/высоту
   экрана.
3. Прописать в `actions`, перезапустить агент, проверить с телефона со
   страницы «Стена» в приложении оператора.

Проверка без робота: `curl http://localhost:8093/healthz` и
`curl -X POST http://localhost:8093/wall/command -H "X-Wall-Token: СЕКРЕТ"
-H "Content-Type: application/json" -d "{\"kind\":\"navigate\",\"nav\":\"next_slide\"}"`.

## Если подрядчик стены даст свой протокол

Модуль отправки на роботе изолирован адаптером (`WallControlPort`) —
пишется новый адаптер под протокол подрядчика, агент не нужен; остальная
система не меняется.
