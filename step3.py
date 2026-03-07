import requests
import pandas as pd

# Загрузка данных из CSV
def load_data(csv_path):
    try:
        data = pd.read_csv(csv_path)
        if 'URL' not in data.columns or 'text' not in data.columns:
            raise ValueError("CSV должен содержать колонки 'URL' и 'text'")
        return data
    except Exception as e:
        print(f"Ошибка загрузки данных: {e}")
        return None

# Формирование промпта
def create_prompt(task_description, data):
    prompt = f"Задача: {task_description}\n\nДанные для обработки:\n"
    for index, row in data.iterrows():
        prompt += f"- URL: {row['URL']}\n  Text: {row['text']}\n"
    return prompt

# Взаимодействие с API Ollama
def call_ollama_api(api_key, prompt, model="default"):
    url = f"http://192.168.31.94:11434/api/generate
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "prompt": prompt
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при запросе к API: {e}")
        return None

# Основная функция
def main():
    # Путь к CSV-файлу и описание задачи
    csv_path = "data.csv"  # Укажите ваш путь к файлу
    task_description = "Проанализируйте тексты и определите ключевые темы"
    
    # API-ключ
    api_key = "ВАШ_API_КЛЮЧ"  # Замените на ваш ключ
    
    # Загрузка данных
    data = load_data(csv_path)
    if data is None:
        return
    
    # Создание промпта
    prompt = create_prompt(task_description, data)
    
    # Запрос к API
    result = call_ollama_api(api_key, prompt)
    if result:
        print("Результат от API Ollama:")
        print(result)

if __name__ == "__main__":
    main()
