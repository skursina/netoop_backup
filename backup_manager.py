import json
import os
import re
from datetime import datetime

import logging
import random

import requests
from tqdm import tqdm
import settings


class CatAPIClient:
    """Класс клиента подключения к сайту с котиками.
    Методы:
    get_all_id(limit=5) - возвращает с сайта информацию о файлах id и тип файла (jpg, png, gif и т.п.).
        Есть лимит на загрузку данных о картинках = 5, но можно увеличить.
        При желании можно выгрузить все картинки.
    get_cat_image_by_id(image_id, text) - возвращает картинку с сайта по номеру id и нанесенной надписью text
    """
    def __init__(self):
        self._base_url = 'https://cataas.com'
        self.logger = logging.getLogger('cataas')
        self.timeout = 30

    def get_all_id(self, limit=10) -> list[tuple[str, str]]:
        """Возвращает список из кортежей (id картинки, тип файла)"""
        try:
            url = self._base_url + '/api/cats'
            headers = {'Accept-Encoding': 'gzip'}
            params = {'limit': limit}

            responses = requests.get(
                url,
                headers=headers,
                params=params,
                stream=True,
                timeout=self.timeout
            )
            responses.raise_for_status()

            total_size = int(responses.headers.get('Content-Light', 0))

            if not total_size:
                print('Что-то пошло не так. Сервер не вернул данные.')
                self.logger.error('Данные об id не получены.')
                return []

            # Прогресс-бар для загрузки json c информацией о файлах про котиков
            with tqdm(
                total=total_size,
                unit='B',
                unit_scale=True,
                desc=f'Скачивание списка с id картинок ...',
                leave=False) as pbar:

                content = bytearray()

                for chunk in responses.iter_content(chunk_size=1024):
                    if chunk:
                        content.extend(chunk)
                        pbar.update(len(chunk))

            cats = json.loads(content.decode('utf-8'))
            cats_result = [(cat['id'], cat['mimetype'][6:]) for cat in cats]
            random.shuffle(cats_result)

            return cats_result

        except requests.exceptions.RequestException as e:
            self.logger.error(f'Ошибка при получении всех id. {e}')
            return []

    def get_cat_image_by_id(self, image_id: str, text: str) -> bytes | None:
        """Возвращает картинку с котиком c нанесенной надписью text"""
        try:
            self.logger.debug(f'Загрузка картинки: {image_id}')

            url = f'{self._base_url}/cat/{image_id}'
            if text:
                url += f'/says/{text}'

            responses = requests.get(url, stream=True, timeout=self.timeout)
            responses.raise_for_status()

            total_size = int(responses.headers.get('content-length', 0))
            image_data = bytearray()

            with tqdm(
                    total=total_size,
                    unit='B',
                    unit_scale=True,
                    desc=f'Скачивание {image_id[:8]}...',
                    leave=False) as pbar:

                # Начинаем загрузку картинки, малыми порциями - это медленно,
                # но иначе сайт может надолго упасть
                for chunk in responses.iter_content(chunk_size=128):
                    if chunk:
                        image_data.extend(chunk)
                        pbar.update(len(chunk))

            return bytes(image_data)

        except requests.exceptions.RequestException as e:
            self.logger.error(f'Ошибка при получении картинки: {e}')


class YandexAPIClient:
    """Класс клиента подключения к Я.Диску"""
    def __init__(self, ya_token: str):
        self._token = ya_token  # Ваш токен для REST API на Я.Диск
        self._base_url = 'https://cloud-api.yandex.net/v1/disk'
        self._headers = {
            'Authorization': f'OAuth {self._token}',
            'Accept': 'application/json',
        }
        self.logger = logging.getLogger('yandex')

    def find_folder(self, folder) -> bool | None:
        """Ищет на Я.Диске папку с именем folder и возвращает True
        - если папка существует,
        - если отсутствует, то папка будет создана """
        try:
            url = self._base_url + '/resources'
            params = {
                'path': folder      # folder = 'disk:/144/'
            }
            response = requests.get(url, headers=self._headers, params=params)

            if response.status_code == 200:
                self.logger.info(f'Папка с именем {folder} уже существует. ')
                return True

            elif response.status_code == 404:
                response = requests.put(url, headers=self._headers, params=params)
                if response.status_code == 201:
                    self.logger.info(f'Папка {folder} успешно создана.')
                    return True
            else:
                self.logger.error(f'Ошибка при проверке папки. Код: {response.status_code}')
                return False

        except requests.exceptions.RequestException as e:
            self.logger.error(f'Ошибка при работе с папкой: {e}')
            return False

    def get_upload_link(self, file: str) -> str:
        """Возвращает для файла file ссылку для загрузки на Я.Диск"""
        try:
            url = self._base_url + '/resources/upload'
            params = {
                'path': file,
                'overwrite': True,
            }
            self.logger.debug(f'Получение ссылки для загрузки: {file}')

            responses = requests.get(url, headers=self._headers, params=params)
            responses.raise_for_status()

            upload_link = responses.json().get('href')

            if upload_link:
                return upload_link

            else:
                self.logger.error(f'Не удалось получить ссылку для загрузки')
                return ''

        except requests.exceptions.RequestException as e:
            self.logger.error(f'Ошибка при получении ссылки для загрузки. {e}')
            return ''

    def upload_image(self, upload_link: str, image_data: bytes) -> bool:
        """Загружает изображение image_data на Я.Диск по ссылке upload_link.
        Загрузка идет порциями chunk из data_generator()
        """
        try:
            total_size = len(image_data)
            with tqdm(
                total=total_size,
                unit='B',
                unit_scale=True,
                desc=f'Загрузка на Я.Диск ...',
                leave=False) as pbar:

                response = requests.put(url=upload_link, data=image_data)
                pbar.update(total_size)

            response.raise_for_status()
            return response.status_code in [201, 202]

        except requests.exceptions.RequestException as e:
            self.logger.error(f'Ошибка при загрузке файла: {e}')
            return False


class BackupManager:
    """Менеджер процесса резервного копирования.
    Его методы:
    run(text, ya_token) - запускает весь процесс резервного копирования на Я.Диск, где
        text - надпись, которая будет нанесена на картинку
        ya_token - REST API токен для Я.Диск
    _save_report(uploaded_files) - записывает собранные данные о загруженных файлах на Я.Диск в json-файл

    Ведется логирование в файл всего процесса.
    """

    def __init__(self, folder: str):
        self.folder = folder
        self.cat_client = CatAPIClient()
        self.disk_client = None
        self._setup_logging()
        self.logger = logging.getLogger('manager')

    def run(self, text: str, ya_token: str) -> dict:
        """Основной метод процесса резервного копирования"""
        result = {
            'folder': self.folder,
            'text': text,
            'ok': False,
            'ok_uploads': 0,
            'report_file': None,
            'message': '',
            'total_files': 0,
            'uploads_files': [],
        }
        uploaded_files = []
        total_files = 0
        ok_uploads = 0

        try:
            print('Начинаем резервное копирование.')

            self.logger.info('Запуск процесса резервного копирования')
            self.logger.info(f"Надпись на картинках: {result['text'] if result['text'] else 'без надписи'}")
            self.logger.info(f'Папка для загрузки на Я.Диск: {self.folder}')

            # Получаем список картинок
            cats_list = self.cat_client.get_all_id()
            if len(cats_list) == 0:
                result['message'] = 'Не удалось получить список картинок'
                return result

            # Создаем папку на Я.Диске
            self.disk_client = YandexAPIClient(ya_token)
            folder_path_ya = f'disk:/{self.folder}/'

            if not self.disk_client.find_folder(folder_path_ya):
                result['message'] = 'Не удалось создать папку на Я.Диске'
                return result

            # Обрабатываем каждую картинку
            for idx, (cat_id, file_type) in enumerate(cats_list, 1):
                self.logger.info(f'Обработка картинки {idx}/{len(cats_list)} id: {cat_id}')

                # Скачиваем картинку
                image_data = self.cat_client.get_cat_image_by_id(cat_id, text)

                if not image_data:
                    self.logger.warning(f'Не удалось получить картинку по id: {cat_id}, пропускаем')
                    continue

                total_files += 1
                image_size = len(image_data)

                # Формируем имя файла
                clean_text = clean_file_name(text) if text else ''
                file_name = f'{cat_id}.{file_type}'
                if clean_text:
                    file_name = f'{clean_text}_{file_name}'

                file_full_name = f'{folder_path_ya}{file_name}'

                # Получаем ссылку для загрузки
                upload_link = self.disk_client.get_upload_link(file_full_name)

                if not upload_link:
                    self.logger.warning(f'Не удалось получить ссылку для загрузки {file_name}')
                    continue

                # Загружаем на Я.Диск
                if self.disk_client.upload_image(upload_link, image_data):
                    ok_uploads += 1
                    file_info = {
                        'file_name': file_name,
                        'size_bytes': image_size,
                    }
                    uploaded_files.append(file_info)
                    self.logger.info(f'Загружен файл {idx}: {file_name} ({len(image_data)} байт)')
                else:
                    self.logger.warning(f'Ошибка загрузки {file_name}')

            # Сохраняем отчет
            if uploaded_files:
                result['report_file'] = self._save_report(uploaded_files)
                result['uploads_files'].extend(uploaded_files)

            result['ok_uploads'] = ok_uploads
            result['total_files'] = total_files
            result['ok'] = ok_uploads > 0

            if result['ok']:
                result['message'] = (f'Успешно загружено {ok_uploads} из {total_files} файлов.'
                                     f'\nФайл с отчетом {result['report_file']} готов.')
            else:
                result['message'] = 'Не удалось загрузить ни одного файла.\nФайл с отчетом отсутствует.'

        except Exception as e:
            self.logger.error(f'Критическая ошибка: {e}')
            result['message'] = str(e)

        except KeyboardInterrupt:
            self.logger.warning("Программа прервана пользователем")
            result['message'] = "Прервано пользователем"
            return result

        return result

    def _setup_logging(self):
        # Настройки процесса логирования
        log_format = '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s'
        log_folder = settings.LOG_FOLDER
        # Создаем папку для логов если ее нет
        os.makedirs(log_folder, exist_ok=True)

        filename = f'{log_folder}/log_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'

        # Настраиваем логгер
        logging.basicConfig(
            level=logging.INFO,
            format=log_format,
            encoding='UTF-8',
            handlers=[
                logging.FileHandler(filename),
                logging.StreamHandler()])

        # Создаем отдельный логгер для экземпляра
        self.logger = logging.getLogger('logging')

    def _save_report(self, uploaded_files: list[dict]) -> str| None:
        """Создает json отчет по загруженным файлам"""

        report = {
            'backup_date': datetime.now().isoformat(),
            'folder': self.folder,
            'total_files': len(uploaded_files),
            'files': uploaded_files,
        }

        report_folder = settings.REPORT_FOLDER
        # Создать папку для отчета если ее нет
        os.makedirs(report_folder, exist_ok=True)

        report_file = f'{report_folder}/report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'

        try:
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            self.logger.info(f'Отчет сохранен в {report_file}')
            return report_file
        except Exception as e:
            self.logger.error(f'Ошибка при сохранении отчета: ',e)

    @staticmethod
    def show_results(result: dict) -> None:
        print('\n' + '=' * 60)
        print('РЕЗУЛЬТАТ ВЫПОЛНЕНИЯ:')
        print('=' * 60)

        if result['ok']:
            print(f'Статус: УСПЕШНО')
            print(f'Папка на Я.Диске: disk:/{result['folder']}/')
            print(f'Всего обработано: {result["total_files"]} картинок')
            print(f'Успешно загружено: {result["ok_uploads"]} файлов')
            if result['report_file']:
                print(f'Отчет сохранен: {result["report_file"]}')
            if result['text']:
                print(f'Надпись на картинках: "{result['text']}"')
        else:
            print('Статус: ОШИБКА')
            print(f'Причина: {result["message"]}')


def clean_file_name(file_name: str) -> str:
    if not file_name:
        return ''
    return re.sub(r'[\\/*?:"<>| ]', '_', file_name)


def main():
    print('=' * 60)
    print('Программа резервного копирования картинок с котиками на Я.Диск')
    print('=' * 60)

    # Папка на Я.Диске для загрузки картинок
    name_forder = settings.GROUP_NUMBER
    if not name_forder:
        name_forder = input('В настройках не указано имя папки для загрузки на Я.Диск.\nВведите сами: ').strip()
        if not name_forder:
            print('Не задано имя папки для загрузки. Программа завершена.')
            return

    text = input('Введите надпись, которую добавим на картинку: ').strip()
    if not text:
        print('Надпись не будет создана.')

    token = input('Введите токен Я.Диска: ').strip()
    if not token:
        print('Токен обязателен. Программа завершена.')
        return

    # Начинаем резервное копирование
    manager = BackupManager(name_forder)
    result = manager.run(text, ya_token=token)

    # Выводим результат
    manager.show_results(result)


if __name__ == "__main__":
    main()