-- Create Spy Love database and app user (run as MySQL root)
CREATE DATABASE IF NOT EXISTS spylove
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'spylove'@'localhost' IDENTIFIED BY 'spylove';
GRANT ALL PRIVILEGES ON spylove.* TO 'spylove'@'localhost';
FLUSH PRIVILEGES;
