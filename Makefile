# make run   — агент одной командой (Telegram-бот или демо)
# make eval  — замер на наборе задач: три конфигурации и таблица
# make test  — тесты без модели и без сети
run:
	docker compose up --build

eval:
	docker compose run --rm --build agent python -m workchat eval strong best nohooks

test:
	docker compose run --rm --build agent python -m pytest -q -p no:cacheprovider tests

down:
	docker compose down
