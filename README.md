# 24spark for OpenWrt

Веб-панель для sing-box на OpenWrt с TProxy, подписками VLESS/Reality,
поддержкой Happ/Remnawave и интеграцией `Службы → 24spark` в LuCI.

## Установка

Подключитесь к роутеру по SSH и выполните:

```sh
wget -O /tmp/24spark-install.sh \
  https://raw.githubusercontent.com/arankarrr/24spark/main/install.sh
sh /tmp/24spark-install.sh
```

После установки откройте LuCI и перейдите в `Службы → 24spark`.
Если пункт не появился в уже открытой сессии, выйдите из LuCI и войдите снова.

Установщик:

- ставит недостающие пакеты через `opkg`;
- создаёт резервную копию заменяемых файлов в `/root/24spark-backup-*`;
- сохраняет существующие `config.json`, подписки и HWID;
- сохраняет и восстанавливает выделение активной ноды;
- проверяет JSON и shell-скрипты до установки;
- проверяет конфигурацию командой `sing-box check`;
- включает автозапуск и запускает сервис.

## Обновление

Повторно запустите команду установки. Пользовательская конфигурация и подписки
останутся на месте.

## Удаление

```sh
BASE_URL=https://raw.githubusercontent.com/arankarrr/24spark/main
wget -qO /tmp/24spark-uninstall.sh "$BASE_URL/uninstall.sh"
sh /tmp/24spark-uninstall.sh
```

Конфигурация и пакет sing-box сохраняются. Для удаления конфигурации используйте
`sh /tmp/24spark-uninstall.sh --purge`.

## Безопасность

Не публикуйте `config.json`, `subscriptions.txt`, `active_node.url`, `happ.hwid`,
VLESS-ссылки или URL подписок. Они исключены из репозитория через `.gitignore`.
