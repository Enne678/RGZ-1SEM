-- Создаём базу данных
CREATE DATABASE finance_bot;

-- Подключаемся к ней
\c finance_bot;

-- Таблица пользователей
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    chat_id BIGINT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS operations (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    chat_id BIGINT NOT NULL,
    type_operation VARCHAR(10) NOT NULL
        CHECK (type_operation IN ('ДОХОД','РАСХОД')),
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_operations_user
        FOREIGN KEY (chat_id) REFERENCES users(chat_id)
        ON DELETE CASCADE
);

-- Индексы для ускорения выборок
CREATE INDEX IF NOT EXISTS idx_users_chat_id
    ON users(chat_id);
CREATE INDEX IF NOT EXISTS idx_operations_chat_id
    ON operations(chat_id);
CREATE INDEX IF NOT EXISTS idx_operations_date
    ON operations(date);
CREATE INDEX IF NOT EXISTS idx_operations_type
    ON operations(type_operation);