import requests
from bs4 import BeautifulSoup
import csv
import time
from datetime import datetime
import logging

# Настройка логгера
logging.basicConfig(filename='log.txt', level=logging.ERROR, format='%(asctime)s - %(message)s')

# Функция для получения содержимого тега <title>
def get_title(url, headers):
    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        title = soup.title.string
        return title
    except Exception as e:
        logging.error(f"Произошла ошибка при обращении к {url}: {str(e)}")
        return f"error:{str(e)}"

# Функция для чтения списка URL из файла в csv-формате
def read_urls_from_csv(input_file):
    try:
        with open(input_file, 'r') as csvfile:
            reader = csv.reader(csvfile)
            urls = []
            for row in reader:
                urls.append(row[0])
        return urls
    except Exception as e:
        logging.error(f"Произошла ошибка при чтении файла {input_file}: {str(e)}")
        return []

# Функция для записи результатов в другой файл в формате URL; title
def write_results_to_csv(output_file, results):
    try:
        with open(output_file, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["URL", "title"])
            for result in results:
                writer.writerow(result)
    except Exception as e:
        logging.error(f"Произошла ошибка при записи в файл {output_file}: {str(e)}")

# Основная функция
def main():
    print("Starting script...")

    # Читаем количество строк в input.csv
    try:
        with open('input.csv', 'r') as csvfile:
            reader = csv.reader(csvfile)
            num_rows = len(list(reader))
        print(f"Found {num_rows} rows in input.csv")
    except Exception as e:
        logging.error(f"Произошла ошибка при чтении файла input.csv: {str(e)}")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Referer': 'https://google.com',
        'Connection': 'keep-alive'
    }

    input_file = 'input.csv'
    output_file = 'output.csv'

    urls = read_urls_from_csv(input_file)
    results = []

    for i, url in enumerate(urls):
        try:
            title = get_title(url, headers=headers)
            results.append((url, title))
            print(f"Processing link # {i+1} out of {len(urls)}")
            
            if e:  # если ошибка возникла
                logging.error(f"Произошла ошибка при обработке ссылки {url}: {str(e)}")
                with open('log.txt', 'a') as f:
                    f.write(f"Error at URL {url} on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. Message: {e}\n")
        except Exception as e:
            logging.error(f"Произошла ошибка при обработке ссылки {url}: {str(e)}")
            with open('log.txt', 'a') as f:
                f.write(f"Error at URL {url} on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. Message: {e}\n")

        time.sleep(1)  # пауза в секунду

    write_results_to_csv(output_file, results)

    print("Script finished!")

if __name__ == "__main__":
    main()