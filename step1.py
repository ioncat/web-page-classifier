import os
import re
import csv

# Название входного и выходного файлов
input_file = 'raw_links.txt'
output_file = 'clean_links.csv'

# Диагностика текущей директории и списка файлов
current_dir = os.getcwd()
print(f"Текущий каталог: {current_dir}")
print(f"Список файлов: {os.listdir(current_dir)}")

# Проверка наличия входного файла
if not os.path.exists(input_file):
    print(f"Ошибка: Файл '{input_file}' не найден. Убедитесь, что он находится в текущем каталоге.")
    exit(1)

# Регулярное выражение для извлечения ссылок
link_pattern = r'https?://[^\s|]+'

# Чтение данных из файла
with open(input_file, 'r', encoding='utf-8') as file:
    raw_data = file.read()

# Извлечение ссылок
links = re.findall(link_pattern, raw_data)

# Сохранение ссылок в файл CSV
with open(output_file, 'w', encoding='utf-8', newline='') as file:
    writer = csv.writer(file)
    writer.writerow(["Link"])  # Заголовок CSV
    for link in links:
        writer.writerow([link])

print(f'Ссылки успешно сохранены в {output_file}.')
