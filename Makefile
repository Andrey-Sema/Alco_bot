.PHONY: up down logs dump

up:
	@echo "Поднимаем базу данных..."
	docker-compose up -d db
	@echo "База поднята. Если хочешь запустить бота локально: python app/main.py"

down:
	@echo "Тушим всё..."
	docker-compose down

logs:
	@echo "Читаем логи базы данных..."
	docker-compose logs -f db

dump:
	@echo "Генерируем дамп кода..."
	python dump_project.py